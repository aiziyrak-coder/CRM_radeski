import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.patients import service
from app.modules.patients.constants import FERGANA_DISTRICTS
from app.modules.patients.models import Patient, PatientKind, PatientPhone, Source
from app.modules.patients.schemas import (
    CategoryIn,
    DoNotCallIn,
    DuplicateCandidate,
    DuplicateCheckIn,
    MergeIn,
    PatientCreate,
    PatientListItem,
    PatientOut,
    PatientPage,
    PatientSort,
    PatientUpdate,
    PhoneIn,
    PhoneUpdate,
    TagCount,
)
from app.modules.users.models import Role, User

# Doctors get their own patient views with the scheduling module; owners see aggregates only.
STAFF = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN)

router = APIRouter(prefix="/patients", tags=["patients"])

Staff = Annotated[User, Depends(require_roles(*STAFF))]
Merger = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


async def _get_patient(session: SessionDep, patient_id: uuid.UUID) -> Patient:
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    return patient


def _live_or_409(patient: Patient) -> None:
    if patient.merged_into_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="patient_merged")


def _get_phone(patient: Patient, phone_id: uuid.UUID) -> PatientPhone:
    phone = next((p for p in patient.phones if p.id == phone_id), None)
    if phone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="phone_not_found")
    return phone


@router.get("/meta/districts")
async def districts(_: Staff) -> list[str]:
    return list(FERGANA_DISTRICTS)


@router.get("/meta/tags")
async def tags(session: SessionDep, _: Staff) -> list[TagCount]:
    """Tags in use, most frequent first (filter and autocomplete on the card)."""
    return [TagCount(tag=t, count=n) for t, n in await service.tag_counts(session)]


@router.get("")
async def list_patients(
    session: SessionDep,
    _: Staff,
    q: Annotated[str | None, Query(max_length=100)] = None,
    kind: PatientKind | None = None,
    category: Annotated[str | None, Query(max_length=50)] = None,
    # a district name, or "-" for records without one
    district: Annotated[str | None, Query(max_length=100)] = None,
    source: Source | None = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    has_phone: bool | None = None,
    sort: PatientSort | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PatientPage:
    """TZ 5: no export here — the list pages through at most 100 rows at a time."""
    filters = service.PatientFilters(
        kind=kind, category=category, district=district, source=source, tag=tag,
        has_phone=has_phone,
    )  # fmt: skip
    total, rows = await service.search(session, q, kind, limit, offset, filters=filters, sort=sort)
    upcoming = await service.next_visits(session, [p.id for p in rows])
    items = []
    for p in rows:
        item = PatientListItem.model_validate(p)
        item.next_visit_at = upcoming.get(p.id)
        items.append(item)
    return PatientPage(total=total, items=items)


@router.post("/check-duplicates")
async def check_duplicates(
    body: DuplicateCheckIn, session: SessionDep, _: Staff
) -> list[DuplicateCandidate]:
    return await service.find_duplicates(session, body.full_name, body.birth_date, body.phones)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "possible duplicates; resend with force=true"}},
)
async def create_patient(
    body: PatientCreate,
    request: Request,
    session: SessionDep,
    user: Staff,
    force: bool = False,
) -> PatientOut:
    if not force:
        dupes = await service.find_duplicates(
            session, body.full_name, body.birth_date, [p.number for p in body.phones]
        )
        if dupes:
            return JSONResponse(  # type: ignore[return-value]
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "possible_duplicates",
                    "candidates": [d.model_dump(mode="json") for d in dupes],
                },
            )

    patient = await service.create_patient(session, body, created_by=user.id)
    audit.record(
        session,
        "patient.create",
        user_id=user.id,
        entity="patient",
        entity_id=patient.id,
        after={**service.snapshot(patient), "forced": force},
        ip=client_ip(request),
    )
    await session.commit()
    return PatientOut.model_validate(patient)


@router.get("/{patient_id}")
async def get_patient(
    patient_id: uuid.UUID, request: Request, session: SessionDep, user: Staff
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    # TZ 5: opening a patient card is audited
    audit.record(
        session,
        "patient.view",
        user_id=user.id,
        entity="patient",
        entity_id=patient.id,
        ip=client_ip(request),
    )
    await session.commit()
    out = PatientOut.model_validate(patient)
    out.first_contact_at, out.first_contact_channel = await service.first_contact(session, patient)
    return out


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    request: Request,
    session: SessionDep,
    user: Staff,
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    before = service.snapshot(patient)
    service.apply_update(patient, body)
    audit.record(
        session,
        "patient.update",
        user_id=user.id,
        entity="patient",
        entity_id=patient.id,
        before=before,
        after=service.snapshot(patient),
        ip=client_ip(request),
    )
    await session.commit()
    return PatientOut.model_validate(patient)


@router.put("/{patient_id}/do-not-call")
async def set_do_not_call(
    patient_id: uuid.UUID,
    body: DoNotCallIn,
    request: Request,
    session: SessionDep,
    user: Staff,
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    await service.set_do_not_call(session, patient, body.do_not_call, body.reason)
    audit.record(
        session,
        "patient.do_not_call",
        user_id=user.id,
        entity="patient",
        entity_id=patient.id,
        after={"do_not_call": body.do_not_call, "reason": patient.do_not_call_reason},
        ip=client_ip(request),
    )
    await session.commit()
    return PatientOut.model_validate(patient)


# --- diagnosis categories (TZ 4.1: shown and edited on the card) ---------------------------


async def _categories_changed(
    session: SessionDep, request: Request, user: User, patient: Patient, before: list[str]
) -> PatientOut:
    audit.record(
        session, "patient.categories", user_id=user.id, entity="patient", entity_id=patient.id,
        before={"categories": before}, after={"categories": patient.categories},
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return PatientOut.model_validate(patient)


@router.post("/{patient_id}/categories")
async def add_category(
    patient_id: uuid.UUID, body: CategoryIn, request: Request, session: SessionDep, user: Staff
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    before = patient.categories
    try:
        await service.add_category(session, patient, body.code)
    except service.CategoryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code) from None
    return await _categories_changed(session, request, user, patient, before)


@router.delete("/{patient_id}/categories/{code}")
async def remove_category(
    patient_id: uuid.UUID, code: str, request: Request, session: SessionDep, user: Staff
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    before = patient.categories
    try:
        await service.remove_category(session, patient, code)
    except service.CategoryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.code) from None
    return await _categories_changed(session, request, user, patient, before)


# --- phones -----------------------------------------------------------------------------------


async def _phones_changed(
    session: SessionDep, request: Request, user: User, patient: Patient, before: dict
) -> PatientOut:
    audit.record(
        session,
        "patient.phones",
        user_id=user.id,
        entity="patient",
        entity_id=patient.id,
        before={"phones": before["phones"]},
        after={"phones": service.snapshot(patient)["phones"]},
        ip=client_ip(request),
    )
    await session.commit()
    return PatientOut.model_validate(patient)


@router.post("/{patient_id}/phones", status_code=status.HTTP_201_CREATED)
async def add_phone(
    patient_id: uuid.UUID, body: PhoneIn, request: Request, session: SessionDep, user: Staff
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    before = service.snapshot(patient)
    await service.add_phone(session, patient, body)
    return await _phones_changed(session, request, user, patient, before)


@router.patch("/{patient_id}/phones/{phone_id}")
async def update_phone(
    patient_id: uuid.UUID,
    phone_id: uuid.UUID,
    body: PhoneUpdate,
    request: Request,
    session: SessionDep,
    user: Staff,
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    phone = _get_phone(patient, phone_id)
    before = service.snapshot(patient)
    if body.is_primary:
        service.set_primary(patient, phone)
    if "note" in body.model_fields_set:
        phone.note = body.note
    return await _phones_changed(session, request, user, patient, before)


@router.delete("/{patient_id}/phones/{phone_id}")
async def delete_phone(
    patient_id: uuid.UUID,
    phone_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    user: Staff,
) -> PatientOut:
    patient = await _get_patient(session, patient_id)
    _live_or_409(patient)
    phone = _get_phone(patient, phone_id)
    before = service.snapshot(patient)
    try:
        await service.remove_phone(session, patient, phone)
    except service.LastPhoneError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="last_phone") from None
    return await _phones_changed(session, request, user, patient, before)


# --- merge ------------------------------------------------------------------------------------


@router.post("/{patient_id}/merge")
async def merge_patients(
    patient_id: uuid.UUID,
    body: MergeIn,
    request: Request,
    session: SessionDep,
    user: Merger,
) -> PatientOut:
    target, source = await service.lock_pair(session, patient_id, body.source_id)
    if target is None or source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    target_before, source_before = service.snapshot(target), service.snapshot(source)
    try:
        await service.merge(session, target, source)
    except service.MergeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    audit.record(
        session,
        "patient.merge",
        user_id=user.id,
        entity="patient",
        entity_id=target.id,
        before={"target": target_before, "source": source_before, "source_id": str(source.id)},
        after=service.snapshot(target),
        ip=client_ip(request),
    )
    await session.commit()
    return PatientOut.model_validate(target)
