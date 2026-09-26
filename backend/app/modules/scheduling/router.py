import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from app.core import clinic_time
from app.core.deps import CurrentUser, SessionDep, client_ip, require_roles
from app.core.events import emit
from app.modules.audit import service as audit
from app.modules.catalog.models import Doctor, Service
from app.modules.patients.models import Patient, Source
from app.modules.scheduling import service
from app.modules.scheduling.models import (
    Appointment,
    AppointmentStatus,
    DoctorAbsence,
    DoctorSchedule,
    Recommendation,
    RecommendationStatus,
)
from app.modules.users.models import Role, User

router = APIRouter(tags=["scheduling"])

BOOKERS = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN)
Booker = Annotated[User, Depends(require_roles(*BOOKERS))]
Planner = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]
ScheduleReader = Annotated[User, Depends(require_roles(*BOOKERS, Role.DOCTOR))]
# roles allowed to book outside a doctor's working hours (walk-ins, overtime)
OVERRIDE_ROLES = (Role.REGISTRAR, Role.SUPERVISOR, Role.ADMIN)


def _err(exc: service.SchedulingError) -> HTTPException:
    code = status.HTTP_409_CONFLICT
    if exc.code in (
        "patient_not_found",
        "doctor_not_found",
        "service_not_found",
        "branch_not_found",
    ):
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in (
        "invalid_transition",
        "reason_required",
        "multiple_devices",
        "timezone_required",
        "invalid_reference",
    ):
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(code, detail=exc.code)


# --- schemas ----------------------------------------------------------------------------------


class ScheduleRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_id: uuid.UUID
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _order(self) -> "ScheduleRow":
        if self.start_time >= self.end_time:
            raise ValueError("start_after_end")
        return self


class WeeklyIn(BaseModel):
    rows: list[ScheduleRow] = Field(max_length=50)


class AbsenceIn(BaseModel):
    date_from: date
    date_to: date
    reason: str | None = Field(default=None, max_length=255)


class AbsenceOut(AbsenceIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class DoctorScheduleOut(BaseModel):
    rows: list[ScheduleRow]
    absences: list[AbsenceOut]


class SlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime
    doctor_id: uuid.UUID
    doctor_name: str
    resource_id: uuid.UUID | None


class AppointmentIn(BaseModel):
    patient_id: uuid.UUID
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    starts_at: datetime
    source: Source | None = None
    note: str | None = Field(default=None, max_length=2000)
    allow_outside_hours: bool = False


class StatusIn(BaseModel):
    status: AppointmentStatus
    reason: str | None = Field(default=None, max_length=100)


class RescheduleIn(BaseModel):
    starts_at: datetime
    doctor_id: uuid.UUID | None = None
    allow_outside_hours: bool = False


class ServiceLine(BaseModel):
    service_id: uuid.UUID
    name_uz: str
    name_ru: str
    duration_min: int
    price: int | None


class AppointmentOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_phone: str | None
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    doctor_name: str
    resource_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    source: Source | None
    note: str | None
    cancel_reason: str | None
    rescheduled_from_id: uuid.UUID | None
    services: list[ServiceLine]


class RecommendationIn(BaseModel):
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    due_date: date
    service_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID | None
    appointment_id: uuid.UUID | None
    due_date: date
    service_id: uuid.UUID | None
    note: str | None
    status: RecommendationStatus
    created_at: datetime


async def serialize(session: SessionDep, appointments: list[Appointment]) -> list[AppointmentOut]:
    if not appointments:
        return []
    patients = {
        p.id: p
        for p in await session.scalars(
            select(Patient).where(Patient.id.in_({a.patient_id for a in appointments}))
        )
    }
    doctors = {
        d.id: d
        for d in await session.scalars(
            select(Doctor).where(Doctor.id.in_({a.doctor_id for a in appointments}))
        )
    }
    service_ids = {s.service_id for a in appointments for s in a.services}
    services = {
        s.id: s for s in await session.scalars(select(Service).where(Service.id.in_(service_ids)))
    }
    out = []
    for a in appointments:
        p, d = patients.get(a.patient_id), doctors.get(a.doctor_id)
        primary = next((ph for ph in (p.phones if p else []) if ph.is_primary), None)
        out.append(
            AppointmentOut(
                id=a.id,
                patient_id=a.patient_id,
                patient_name=p.full_name if p else "?",
                patient_phone=primary.number if primary else None,
                branch_id=a.branch_id,
                doctor_id=a.doctor_id,
                doctor_name=d.name_uz if d else "?",
                resource_id=a.resource_id,
                starts_at=a.starts_at,
                ends_at=a.ends_at,
                status=a.status,
                source=a.source,
                note=a.note,
                cancel_reason=a.cancel_reason,
                rescheduled_from_id=a.rescheduled_from_id,
                services=[
                    ServiceLine(
                        service_id=line.service_id,
                        name_uz=services[line.service_id].name_uz,
                        name_ru=services[line.service_id].name_ru,
                        duration_min=line.duration_min,
                        price=line.price,
                    )
                    for line in a.services
                    if line.service_id in services
                ],
            )
        )
    return out


async def _appointment(session: SessionDep, appointment_id: uuid.UUID) -> Appointment:
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="appointment_not_found")
    return appointment


async def _doctor_of(session: SessionDep, user: User) -> Doctor | None:
    return await service.doctor_of(session, user)


async def _own_doctor(session: SessionDep, user: User) -> Doctor:
    doctor = await _doctor_of(session, user)
    if doctor is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not_a_doctor")
    return doctor


async def _check_patient_scope(session: SessionDep, user: User, patient_id: uuid.UUID) -> None:
    """Doctors see only patients they have (had) an appointment with."""
    if not await service.can_see_patient(session, user, patient_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")


async def _doctor_or_404(session: SessionDep, doctor_id: uuid.UUID) -> Doctor:
    doctor = await session.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="doctor_not_found")
    return doctor


# --- weekly schedules -------------------------------------------------------------------------


@router.get("/schedule/doctors/{doctor_id}")
async def get_doctor_schedule(
    doctor_id: uuid.UUID, session: SessionDep, _: ScheduleReader
) -> DoctorScheduleOut:
    rows = await session.scalars(
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id == doctor_id)
        .order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
    )
    absences = await session.scalars(
        select(DoctorAbsence)
        .where(DoctorAbsence.doctor_id == doctor_id, DoctorAbsence.date_to >= clinic_time.today())
        .order_by(DoctorAbsence.date_from)
    )
    return DoctorScheduleOut(
        rows=[ScheduleRow.model_validate(r) for r in rows],
        absences=[AbsenceOut.model_validate(a) for a in absences],
    )


@router.put("/schedule/doctors/{doctor_id}/weekly")
async def set_weekly(
    doctor_id: uuid.UUID, body: WeeklyIn, request: Request, session: SessionDep, user: Planner
) -> DoctorScheduleOut:
    await _doctor_or_404(session, doctor_id)
    await session.execute(delete(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
    for row in body.rows:
        session.add(DoctorSchedule(doctor_id=doctor_id, **row.model_dump()))
    audit.record(
        session, "schedule.weekly", user_id=user.id, entity="doctor", entity_id=doctor_id,
        after={"rows": [r.model_dump(mode="json") for r in body.rows]}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return await get_doctor_schedule(doctor_id, session, user)


@router.post("/schedule/doctors/{doctor_id}/absences", status_code=status.HTTP_201_CREATED)
async def add_absence(
    doctor_id: uuid.UUID, body: AbsenceIn, request: Request, session: SessionDep, user: Planner
) -> AbsenceOut:
    if body.date_from > body.date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="from_after_to")
    await _doctor_or_404(session, doctor_id)
    absence = DoctorAbsence(doctor_id=doctor_id, **body.model_dump())
    session.add(absence)
    await session.flush()
    audit.record(
        session, "schedule.absence_add", user_id=user.id, entity="doctor", entity_id=doctor_id,
        after={"id": str(absence.id), **body.model_dump(mode="json")}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return AbsenceOut.model_validate(absence)


@router.delete("/schedule/absences/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_absence(
    absence_id: uuid.UUID, request: Request, session: SessionDep, user: Planner
) -> None:
    absence = await session.get(DoctorAbsence, absence_id)
    if absence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="absence_not_found")
    before = AbsenceOut.model_validate(absence).model_dump(mode="json")
    await session.delete(absence)
    audit.record(
        session, "schedule.absence_delete", user_id=user.id, entity="doctor",
        entity_id=absence.doctor_id, before=before, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()


class WindowOut(BaseModel):
    starts_at: datetime
    ends_at: datetime


class DoctorDayOut(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    color: str | None
    windows: list[WindowOut]


@router.get("/schedule/day")
async def schedule_day(
    session: SessionDep,
    _: ScheduleReader,
    day: Annotated[date, Query(alias="date")],
    branch_id: uuid.UUID,
) -> list[DoctorDayOut]:
    """Columns for the day view: doctors working at the branch that day (or already booked)."""
    booked = {
        a.doctor_id for a in await service.day_appointments(session, day, branch_id=branch_id)
    }
    scheduled = set(
        await session.scalars(
            select(DoctorSchedule.doctor_id).where(
                DoctorSchedule.branch_id == branch_id, DoctorSchedule.weekday == day.weekday()
            )
        )
    )
    ids = booked | scheduled
    if not ids:
        return []
    doctors = await session.scalars(
        select(Doctor).where(Doctor.id.in_(ids)).order_by(Doctor.sort_order, Doctor.name_uz)
    )
    out = []
    for d in doctors:
        windows = await service.working_windows(session, d, branch_id, day)
        out.append(
            DoctorDayOut(
                doctor_id=d.id,
                doctor_name=d.name_uz,
                color=d.color,
                windows=[WindowOut(starts_at=s, ends_at=e) for s, e in windows],
            )
        )
    return out


# --- appointments -----------------------------------------------------------------------------


@router.get("/appointments/day")
async def appointments_day(
    session: SessionDep,
    user: ScheduleReader,
    day: Annotated[date, Query(alias="date")],
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
) -> list[AppointmentOut]:
    if user.role is Role.DOCTOR:
        doctor_id = (await _own_doctor(session, user)).id  # only their own column
    return await serialize(
        session, await service.day_appointments(session, day, branch_id, doctor_id)
    )


@router.get("/appointments/my-day")
async def my_day(
    session: SessionDep, user: CurrentUser, day: Annotated[date | None, Query(alias="date")] = None
) -> list[AppointmentOut]:
    doctor = await _own_doctor(session, user)
    rows = await service.day_appointments(session, day or clinic_time.today(), doctor_id=doctor.id)
    return await serialize(session, rows)


@router.get("/appointments/slots")
async def slots(
    session: SessionDep,
    _: Booker,
    service_ids: Annotated[list[uuid.UUID], Query(min_length=1, max_length=10)],
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    date_from: date | None = None,
    days: Annotated[int, Query(ge=1, le=60)] = 14,
    part: Literal["morning", "afternoon", "evening"] | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
    # when rescheduling: the appointment being moved doesn't count for the course interval
    exclude_appointment_id: uuid.UUID | None = None,
) -> list[SlotOut]:
    try:
        found = await service.find_slots(
            session,
            service_ids=service_ids,
            branch_id=branch_id,
            doctor_id=doctor_id,
            patient_id=patient_id,
            date_from=date_from,
            days=days,
            part_of_day=part,
            limit=limit,
            exclude_appointment_id=exclude_appointment_id,
        )
    except service.SchedulingError as exc:
        raise _err(exc) from None
    names = {
        d.id: d.name_uz
        for d in await session.scalars(
            select(Doctor).where(Doctor.id.in_({s.doctor_id for s in found}))
        )
    }
    return [SlotOut(**s.__dict__, doctor_name=names.get(s.doctor_id, "?")) for s in found]


@router.get("/appointments/patient/{patient_id}")
async def patient_appointments(
    patient_id: uuid.UUID, session: SessionDep, user: ScheduleReader
) -> list[AppointmentOut]:
    await _check_patient_scope(session, user, patient_id)
    rows = await session.scalars(
        select(Appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.starts_at.desc())
        .limit(100)
    )
    return await serialize(session, list(rows))


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentIn, request: Request, session: SessionDep, user: Booker
) -> AppointmentOut:
    if body.allow_outside_hours and user.role not in OVERRIDE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        appointment = await service.create_appointment(
            session,
            patient_id=body.patient_id,
            branch_id=body.branch_id,
            doctor_id=body.doctor_id,
            service_ids=body.service_ids,
            starts_at=body.starts_at,
            source=body.source,
            note=body.note,
            created_by=user.id,
            allow_outside_hours=body.allow_outside_hours,
        )
    except service.SchedulingError as exc:
        raise _err(exc) from None
    audit.record(
        session, "appointment.create", user_id=user.id, entity="appointment",
        entity_id=appointment.id, after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [appointment]))[0]


@router.post("/appointments/{appointment_id}/status")
async def set_status(
    appointment_id: uuid.UUID,
    body: StatusIn,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> AppointmentOut:
    appointment = await _appointment(session, appointment_id)
    if user.role not in BOOKERS:
        # doctors may only mark their own patients as seen
        doctor = await _doctor_of(session, user)
        if not (
            user.role is Role.DOCTOR
            and doctor
            and doctor.id == appointment.doctor_id
            and body.status in (AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    before = appointment.status.value
    try:
        await service.change_status(session, appointment, body.status, reason=body.reason)
    except service.SchedulingError as exc:
        raise _err(exc) from None
    audit.record(
        session, "appointment.status", user_id=user.id, entity="appointment",
        entity_id=appointment.id, before={"status": before},
        after={"status": body.status.value, "reason": body.reason}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [appointment]))[0]


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule(
    appointment_id: uuid.UUID,
    body: RescheduleIn,
    request: Request,
    session: SessionDep,
    user: Booker,
) -> AppointmentOut:
    if body.allow_outside_hours and user.role not in OVERRIDE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    appointment = await _appointment(session, appointment_id)
    try:
        new = await service.reschedule(
            session,
            appointment,
            starts_at=body.starts_at,
            doctor_id=body.doctor_id,
            user_id=user.id,
            allow_outside_hours=body.allow_outside_hours,
        )
    except service.SchedulingError as exc:
        await session.rollback()
        raise _err(exc) from None
    audit.record(
        session, "appointment.reschedule", user_id=user.id, entity="appointment",
        entity_id=new.id, before={"from": str(appointment.id)},
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [new]))[0]


# --- recommendations --------------------------------------------------------------------------


@router.post("/recommendations", status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    body: RecommendationIn, request: Request, session: SessionDep, user: CurrentUser
) -> RecommendationOut:
    if user.role not in (Role.DOCTOR, Role.REGISTRAR, Role.SUPERVISOR, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    patient = await session.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    if patient.merged_into_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="patient_merged")
    appt = None
    if body.appointment_id:
        appt = await session.get(Appointment, body.appointment_id)
        if appt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="appointment_not_found")
        if appt.patient_id != patient.id:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="appointment_patient_mismatch")
    if body.service_id and await session.get(Service, body.service_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="service_not_found")
    doctor = await _doctor_of(session, user)
    if user.role is Role.DOCTOR:
        # a doctor recommends only for their own patients
        if doctor is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not_a_doctor")
        if appt:
            own = appt.doctor_id == doctor.id
        else:
            own = await service.doctor_has_patient(session, doctor.id, patient.id)
        if not own:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    doctor_id = doctor.id if doctor else (appt.doctor_id if appt else None)
    rec = Recommendation(**body.model_dump(), doctor_id=doctor_id, created_by=user.id)
    session.add(rec)
    await session.flush()
    await emit(session, "recommendation.created", recommendation=rec)
    audit.record(
        session, "recommendation.create", user_id=user.id, entity="patient",
        entity_id=body.patient_id, after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return RecommendationOut.model_validate(rec)


@router.get("/recommendations/patient/{patient_id}")
async def patient_recommendations(
    patient_id: uuid.UUID, session: SessionDep, user: ScheduleReader
) -> list[RecommendationOut]:
    await _check_patient_scope(session, user, patient_id)
    rows = await session.scalars(
        select(Recommendation)
        .where(Recommendation.patient_id == patient_id)
        .order_by(Recommendation.due_date.desc())
    )
    return [RecommendationOut.model_validate(r) for r in rows]
