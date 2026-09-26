import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import phone_digits_query, search_key
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.patients.schemas import (
    DuplicateCandidate,
    PatientCreate,
    PatientListItem,
    PatientUpdate,
    PhoneIn,
)

# same person if names are this similar (pg_trgm, 0..1) and birth dates agree
NAME_DUPLICATE_SIMILARITY = 0.75

AUDITED_FIELDS = (
    "full_name", "birth_date", "gender", "address", "district", "language", "source", "tags",
    "notes", "do_not_call", "do_not_call_reason",
)  # fmt: skip


class LastPhoneError(Exception):
    pass


class MergeError(Exception):
    pass


def snapshot(p: Patient) -> dict[str, Any]:
    data = {f: getattr(p, f) for f in AUDITED_FIELDS}
    data["phones"] = sorted(ph.number for ph in p.phones)
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in data.items()}


def _live() -> Any:
    return Patient.merged_into_id.is_(None)


# --- duplicates -------------------------------------------------------------------------------


async def find_duplicates(
    session: AsyncSession,
    full_name: str,
    birth_date: date | None,
    numbers: list[str],
    exclude_id: uuid.UUID | None = None,
) -> list[DuplicateCandidate]:
    reasons: dict[uuid.UUID, set[str]] = {}

    if numbers:
        rows = await session.execute(
            select(PatientPhone.patient_id)
            .join(Patient)
            .where(PatientPhone.number.in_(numbers), _live())
        )
        for (pid,) in rows:
            reasons.setdefault(pid, set()).add("phone")

    key = search_key(full_name)
    if len(key) >= 3:
        similar = func.similarity(Patient.search_key, key) >= NAME_DUPLICATE_SIMILARITY
        if birth_date:
            same_person = or_(
                and_(similar, Patient.birth_date == birth_date),
                and_(Patient.search_key == key, Patient.birth_date.is_(None)),
            )
        else:
            # without a birth date only an identical (normalized) name counts
            same_person = Patient.search_key == key
        rows = await session.execute(select(Patient.id).where(same_person, _live()).limit(20))
        for (pid,) in rows:
            reasons.setdefault(pid, set()).add("name")

    reasons.pop(exclude_id, None)  # type: ignore[arg-type]
    if not reasons:
        return []
    patients = await session.scalars(select(Patient).where(Patient.id.in_(reasons)))
    return [
        DuplicateCandidate(
            **PatientListItem.model_validate(p).model_dump(), reasons=sorted(reasons[p.id])
        )
        for p in patients
    ]


# --- create / update --------------------------------------------------------------------------


def _phones(items: list[PhoneIn]) -> list[PatientPhone]:
    seen: dict[str, PatientPhone] = {}
    for item in items:
        if item.number not in seen:
            seen[item.number] = PatientPhone(
                number=item.number, is_primary=item.is_primary, note=item.note
            )
    phones = list(seen.values())
    if phones and not any(p.is_primary for p in phones):
        phones[0].is_primary = True
    elif sum(p.is_primary for p in phones) > 1:
        first = next(p for p in phones if p.is_primary)
        for p in phones:
            p.is_primary = p is first
    return phones


async def create_patient(
    session: AsyncSession,
    data: PatientCreate,
    created_by: uuid.UUID | None,
    kind: PatientKind = PatientKind.ACTIVE,
) -> Patient:
    patient = Patient(
        **data.model_dump(exclude={"phones"}),
        search_key=search_key(data.full_name),
        kind=kind,
        created_by=created_by,
        phones=_phones(data.phones),
    )
    session.add(patient)
    await session.flush()
    return patient


def apply_update(patient: Patient, data: PatientUpdate) -> None:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("full_name", "gender", "language", "tags") and value is None:
            continue  # required columns can't be cleared
        setattr(patient, field, value)
    patient.search_key = search_key(patient.full_name)


async def add_phone(session: AsyncSession, patient: Patient, item: PhoneIn) -> PatientPhone:
    existing = next((p for p in patient.phones if p.number == item.number), None)
    if existing:
        return existing
    phone = PatientPhone(number=item.number, is_primary=item.is_primary, note=item.note)
    if phone.is_primary or not patient.phones:
        for p in patient.phones:
            p.is_primary = False
        phone.is_primary = True
    patient.phones.append(phone)
    await session.flush()
    return phone


def set_primary(patient: Patient, phone: PatientPhone) -> None:
    for p in patient.phones:
        p.is_primary = p is phone


async def remove_phone(session: AsyncSession, patient: Patient, phone: PatientPhone) -> None:
    if len(patient.phones) <= 1:
        raise LastPhoneError
    was_primary = phone.is_primary
    patient.phones.remove(phone)
    if was_primary:
        patient.phones[0].is_primary = True
    await session.flush()


# --- search -----------------------------------------------------------------------------------


def _search_query(q: str | None, kind: PatientKind | None) -> tuple[Select, Any]:
    stmt = select(Patient).where(_live())
    order: Any = Patient.full_name
    if kind:
        stmt = stmt.where(Patient.kind == kind)
    if not q or not q.strip():
        return stmt, order

    if digits := phone_digits_query(q):
        matching = select(PatientPhone.patient_id).where(PatientPhone.number.contains(digits))
        return stmt.where(Patient.id.in_(matching)), order

    key = search_key(q)
    words = key.split()
    all_words = and_(*(Patient.search_key.contains(w) for w in words))
    fuzzy = Patient.search_key.op("%")(key)  # pg_trgm similarity (index-backed)
    stmt = stmt.where(or_(all_words, fuzzy))
    return stmt, func.similarity(Patient.search_key, key).desc()


async def search(
    session: AsyncSession,
    q: str | None,
    kind: PatientKind | None,
    limit: int,
    offset: int,
) -> tuple[int, list[Patient]]:
    stmt, order = _search_query(q, kind)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.order_by(order, Patient.id).limit(limit).offset(offset))
    return total or 0, list(rows)


# --- merge ------------------------------------------------------------------------------------

# Modules that reference patients (appointments, calls, tasks, ...) register a hook here that
# re-points their rows from the merged patient to the surviving one.
MergeHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]
MERGE_HOOKS: list[MergeHook] = []


async def merge(session: AsyncSession, target: Patient, source: Patient) -> None:
    """Folds `source` into `target`; `source` stays as a tombstone pointing at `target`."""
    if target.id == source.id:
        raise MergeError("same_patient")
    if target.merged_into_id or source.merged_into_id:
        raise MergeError("already_merged")

    for field in ("birth_date", "address", "district", "source"):
        if getattr(target, field) is None and getattr(source, field) is not None:
            setattr(target, field, getattr(source, field))
    if target.gender.value == "unknown":
        target.gender = source.gender
    if source.notes:
        target.notes = f"{target.notes}\n{source.notes}" if target.notes else source.notes
    target.tags = sorted(set(target.tags) | set(source.tags))
    if source.do_not_call and not target.do_not_call:
        target.do_not_call = True
        target.do_not_call_reason = source.do_not_call_reason
    if source.last_visit_at and (
        target.last_visit_at is None or source.last_visit_at > target.last_visit_at
    ):
        target.last_visit_at = source.last_visit_at
    # a merged record that had real activity makes the survivor an active patient
    if PatientKind.ACTIVE in (source.kind, target.kind):
        target.kind = PatientKind.ACTIVE

    known = {p.number for p in target.phones}
    for phone in list(source.phones):
        if phone.number not in known:
            source.phones.remove(phone)
            phone.is_primary = False
            target.phones.append(phone)
            known.add(phone.number)

    for hook in MERGE_HOOKS:
        await hook(session, target.id, source.id)

    source.merged_into_id = target.id
    await session.flush()
