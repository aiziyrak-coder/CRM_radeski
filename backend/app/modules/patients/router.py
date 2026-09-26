import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.patients import service
from app.modules.patients.constants import FERGANA_DISTRICTS
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.patients.schemas import (
    DoNotCallIn,
    DuplicateCandidate,
    DuplicateCheckIn,
    MergeIn,
    PatientCreate,
    PatientListItem,
    PatientOut,
    PatientPage,
    PatientUpdate,
    PhoneIn,
    PhoneUpdate,
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


@router.get("")
async def list_patients(
    session: SessionDep,
    _: Staff,
    q: Annotated[str | None, Query(max_length=100)] = None,
    kind: PatientKind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PatientPage:
    total, rows = await service.search(session, q, kind, limit, offset)
    return PatientPage(total=total, items=[PatientListItem.model_validate(p) for p in rows])


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
    return PatientOut.model_validate(patient)


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
    patient.do_not_call = body.do_not_call
    patient.do_not_call_reason = body.reason if body.do_not_call else None
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
    target = await _get_patient(session, patient_id)
    source = await _get_patient(session, body.source_id)
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
