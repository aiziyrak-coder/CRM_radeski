import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.events import emit
from app.core.text import phone_digits_query, search_key
from app.modules.patients.models import (
    MANUAL_CONDITION,
    Patient,
    PatientCondition,
    PatientKind,
    PatientPhone,
    Source,
)
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
        conditions=[],  # initialized so serializing never triggers a lazy load
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


async def set_do_not_call(
    session: AsyncSession, patient: Patient, do_not_call: bool, reason: str | None
) -> None:
    """The only way to change the flag; turning it on emits `patient.do_not_call_set` so open
    outbound call tasks get cancelled (tasks/rules.py)."""
    patient.do_not_call = do_not_call
    patient.do_not_call_reason = reason if do_not_call else None
    await session.flush()
    if do_not_call:
        await emit(session, "patient.do_not_call_set", patient=patient)


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

# the list's "no district" option (data-quality view: the legacy address didn't parse)
NO_DISTRICT = "-"


@dataclass(frozen=True)
class PatientFilters:
    kind: PatientKind | None = None
    category: str | None = None
    district: str | None = None
    source: Source | None = None
    tag: str | None = None
    has_phone: bool | None = None


def _next_visit() -> Any:
    """The patient's nearest booked visit (correlated subquery, also used for sorting)."""
    from app.modules.scheduling.models import Appointment, AppointmentStatus

    return (
        select(func.min(Appointment.starts_at))
        .where(
            Appointment.patient_id == Patient.id,
            Appointment.starts_at > clinic_time.now(),
            Appointment.status.in_((AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED)),
        )
        .correlate(Patient)
        .scalar_subquery()
    )


SORTS: dict[str, Callable[[], Any]] = {
    "name": lambda: Patient.full_name,
    "last_visit": lambda: Patient.last_visit_at.desc().nulls_last(),
    "next_visit": lambda: _next_visit().asc().nulls_last(),
    "created": lambda: Patient.created_at.desc(),
    "birth_date": lambda: Patient.birth_date.asc().nulls_last(),
}


def _search_query(q: str | None, f: PatientFilters, sort: str | None = None) -> tuple[Select, Any]:
    stmt = select(Patient).where(_live())
    order: Any = SORTS[sort]() if sort else Patient.full_name
    if f.kind:
        stmt = stmt.where(Patient.kind == f.kind)
    if f.category:
        with_category = select(PatientCondition.patient_id).where(
            PatientCondition.category_code == f.category
        )
        stmt = stmt.where(Patient.id.in_(with_category))
    if f.district == NO_DISTRICT:
        stmt = stmt.where(Patient.district.is_(None))
    elif f.district:
        stmt = stmt.where(Patient.district == f.district)
    if f.source:
        stmt = stmt.where(Patient.source == f.source)
    if f.tag:
        stmt = stmt.where(Patient.tags.contains([f.tag]))
    if f.has_phone is not None:
        with_phone = exists().where(PatientPhone.patient_id == Patient.id)
        stmt = stmt.where(with_phone if f.has_phone else ~with_phone)
    if not q or not q.strip():
        if not f.kind:
            # the cold base is ~45k nameless numbers; browse it only when asked for explicitly
            stmt = stmt.where(Patient.kind != PatientKind.COLD)
        return stmt, order

    if digits := phone_digits_query(q):
        matching = select(PatientPhone.patient_id).where(PatientPhone.number.contains(digits))
        return stmt.where(Patient.id.in_(matching)), order

    key = search_key(q)
    words = key.split()
    all_words = and_(*(Patient.search_key.contains(w) for w in words))
    fuzzy = Patient.search_key.op("%")(key)  # pg_trgm similarity (index-backed)
    stmt = stmt.where(or_(all_words, fuzzy))
    # the best name match first, unless the user picked a column to sort by
    return stmt, order if sort else func.similarity(Patient.search_key, key).desc()


async def search(
    session: AsyncSession,
    q: str | None,
    kind: PatientKind | None,
    limit: int,
    offset: int,
    category: str | None = None,
    *,
    filters: PatientFilters | None = None,
    sort: str | None = None,
) -> tuple[int, list[Patient]]:
    f = filters or PatientFilters(kind=kind, category=category)
    stmt, order = _search_query(q, f, sort)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.order_by(order, Patient.id).limit(limit).offset(offset))
    return total or 0, list(rows)


async def next_visits(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    if not ids:
        return {}
    rows = await session.execute(select(Patient.id, _next_visit()).where(Patient.id.in_(ids)))
    return {pid: at for pid, at in rows if at is not None}


async def tag_counts(session: AsyncSession, limit: int = 100) -> list[tuple[str, int]]:
    inner = select(func.unnest(Patient.tags).label("tag")).where(_live()).subquery()
    rows = await session.execute(
        select(inner.c.tag, func.count())
        .group_by(inner.c.tag)
        .order_by(func.count().desc(), inner.c.tag)
        .limit(limit)
    )
    return [(t, n) for t, n in rows]


# --- card extras ------------------------------------------------------------------------------


async def first_contact(
    session: AsyncSession, patient: Patient
) -> tuple[datetime | None, str | None]:
    """The earliest trace of the person: an inquiry, a call, or registration in the CRM
    (imported records have no first-contact date unless they got in touch since)."""
    from app.modules.leads.models import Lead
    from app.modules.telephony.models import Call

    candidates: list[tuple[datetime, str]] = []
    lead = (
        await session.execute(
            select(Lead.created_at, Lead.channel)
            .where(Lead.patient_id == patient.id)
            .order_by(Lead.created_at)
            .limit(1)
        )
    ).first()
    if lead:
        candidates.append((lead[0], lead[1].value))
    call = await session.scalar(
        select(func.min(Call.started_at)).where(Call.patient_id == patient.id)
    )
    if call:
        candidates.append((call, "call"))
    if patient.kind not in (PatientKind.LEGACY, PatientKind.COLD):
        candidates.append((patient.created_at, "registered"))
    if not candidates:
        return None, None
    return min(candidates, key=lambda c: c[0])


class CategoryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def add_category(session: AsyncSession, patient: Patient, code: str) -> None:
    """A diagnosis category set by staff on the card (idempotent)."""
    from app.modules.diagnoses.categories import CATEGORY_BY_CODE

    category = CATEGORY_BY_CODE.get(code)
    if category is None:
        raise CategoryError("unknown_category")
    if code in patient.categories:
        return
    patient.conditions.append(
        PatientCondition(
            raw_text=category.name_uz, category_code=code, source=MANUAL_CONDITION, text_key=None
        )
    )
    await session.flush()


async def remove_category(session: AsyncSession, patient: Patient, code: str) -> None:
    """Only categories set on the card are removed here; an imported diagnosis keeps its text
    and is re-categorised on the diagnoses page (the mapping applies to every patient)."""
    manual = [
        c for c in patient.conditions if c.category_code == code and c.source == MANUAL_CONDITION
    ]
    if not manual:
        if code in patient.categories:
            raise CategoryError("category_from_import")
        return
    for c in manual:
        patient.conditions.remove(c)
    await session.flush()


# --- merge ------------------------------------------------------------------------------------

# Modules that reference patients (appointments, calls, tasks, ...) register a hook here that
# re-points their rows from the merged patient to the surviving one.
MergeHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]
MERGE_HOOKS: list[MergeHook] = []


async def lock_pair(
    session: AsyncSession, first_id: uuid.UUID, second_id: uuid.UUID
) -> tuple[Patient | None, Patient | None]:
    """Row-locks both patients (always in id order, so two concurrent merges of the same pair
    can't deadlock) and reloads them, so checks see what other transactions committed."""
    locked: dict[uuid.UUID, Patient | None] = {}
    for pid in sorted({first_id, second_id}):
        locked[pid] = await session.scalar(
            select(Patient)
            .where(Patient.id == pid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return locked[first_id], locked[second_id]


async def merge(session: AsyncSession, target: Patient, source: Patient) -> None:
    """Folds `source` into `target`; `source` stays as a tombstone pointing at `target`.
    Callers lock both rows first (lock_pair)."""
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

    for condition in list(source.conditions):
        source.conditions.remove(condition)
        target.conditions.append(condition)

    for hook in MERGE_HOOKS:
        await hook(session, target.id, source.id)

    source.merged_into_id = target.id
    await session.flush()
    if target.do_not_call:
        # the source's open call tasks now belong to a do-not-call patient
        await emit(session, "patient.do_not_call_set", patient=target)
