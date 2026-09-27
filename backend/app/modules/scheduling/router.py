import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from app.core import clinic_time
from app.core.deps import CurrentUser, SessionDep, client_ip, require_roles
from app.core.events import emit
from app.modules.audit import service as audit
from app.modules.catalog.models import Doctor, Resource, ResourceKind, Service
from app.modules.diagnoses.categories import CATEGORIES
from app.modules.patients.models import Gender, Patient, PatientCondition, PatientKind, Source
from app.modules.scheduling import service
from app.modules.scheduling.models import (
    AbsenceKind,
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
        "resource_not_found",
    ):
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in (
        "invalid_transition",
        "reason_required",
        "multiple_devices",
        "timezone_required",
        "invalid_reference",
        "device_required",
        "wrong_device",
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

    @model_validator(mode="after")
    def _no_overlap(self) -> "WeeklyIn":
        # a break is the gap between two rows of a day; overlapping rows are a typo
        by_day: dict[int, list[ScheduleRow]] = defaultdict(list)
        for row in self.rows:
            by_day[row.weekday].append(row)
        for rows in by_day.values():
            rows.sort(key=lambda r: r.start_time)
            if any(a.end_time > b.start_time for a, b in zip(rows, rows[1:], strict=False)):
                raise ValueError("rows_overlap")
        return self


class CopyScheduleIn(BaseModel):
    doctor_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class AbsenceIn(BaseModel):
    date_from: date
    date_to: date
    kind: AbsenceKind = AbsenceKind.OTHER
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


class ResourceIn(BaseModel):
    resource_id: uuid.UUID | None


class AppointmentOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_phone: str | None
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    doctor_name: str
    resource_id: uuid.UUID | None
    resource_name: str | None = None
    resource_kind: ResourceKind | None = None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    source: Source | None
    note: str | None
    cancel_reason: str | None
    rescheduled_from_id: uuid.UUID | None
    # when the visit it was moved from was planned (the panel links to it)
    rescheduled_from_starts_at: datetime | None = None
    # a moved ("rescheduled") visit points to its new time
    rescheduled_to_id: uuid.UUID | None = None
    rescheduled_to_starts_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    created_at: datetime | None = None
    status_changed_at: datetime | None = None
    services: list[ServiceLine]


class RecommendationIn(BaseModel):
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    due_date: date
    service_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class RecommendationUpdate(BaseModel):
    due_date: date | None = None
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
    doctor_name: str | None = None
    service_name_uz: str | None = None
    service_name_ru: str | None = None
    # the current user may edit / withdraw it (their own, still open)
    can_edit: bool = False


class ContextPatient(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    birth_date: date | None
    gender: Gender
    kind: PatientKind
    tags: list[str]
    notes: str | None
    last_visit_at: datetime | None


class ContextCondition(BaseModel):
    raw_text: str
    category_code: str | None
    category_name_uz: str | None
    category_name_ru: str | None
    visit_type: str | None


class PatientContextOut(BaseModel):
    """What a doctor needs at the visit: diagnoses, past visits, earlier recommendations."""

    patient: ContextPatient
    conditions: list[ContextCondition]
    visits: list[AppointmentOut]
    recommendations: list[RecommendationOut]


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
    resources = {
        r.id: r
        for r in await session.scalars(
            select(Resource).where(Resource.id.in_({a.resource_id for a in appointments}))
        )
    }
    authors = dict(
        (
            await session.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({a.created_by for a in appointments})
                )
            )
        ).all()
    )
    ids = {a.id for a in appointments}
    moved_from = dict(
        (
            await session.execute(
                select(Appointment.id, Appointment.starts_at).where(
                    Appointment.id.in_({a.rescheduled_from_id for a in appointments})
                )
            )
        ).all()
    )
    moved_to = {
        src: (new_id, starts)
        for new_id, src, starts in await session.execute(
            select(Appointment.id, Appointment.rescheduled_from_id, Appointment.starts_at).where(
                Appointment.rescheduled_from_id.in_(ids)
            )
        )
    }
    out = []
    for a in appointments:
        p, d = patients.get(a.patient_id), doctors.get(a.doctor_id)
        primary = next((ph for ph in (p.phones if p else []) if ph.is_primary), None)
        res = resources.get(a.resource_id) if a.resource_id else None
        to_id, to_starts = moved_to.get(a.id, (None, None))
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
                resource_name=res.name if res else None,
                resource_kind=res.kind if res else None,
                starts_at=a.starts_at,
                ends_at=a.ends_at,
                status=a.status,
                source=a.source,
                note=a.note,
                cancel_reason=a.cancel_reason,
                rescheduled_from_id=a.rescheduled_from_id,
                rescheduled_from_starts_at=moved_from.get(a.rescheduled_from_id),
                rescheduled_to_id=to_id,
                rescheduled_to_starts_at=to_starts,
                created_by=a.created_by,
                created_by_name=authors.get(a.created_by),
                created_at=a.created_at,
                status_changed_at=a.status_changed_at,
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


@router.post("/schedule/doctors/{doctor_id}/copy")
async def copy_weekly(
    doctor_id: uuid.UUID,
    body: CopyScheduleIn,
    request: Request,
    session: SessionDep,
    user: Planner,
) -> dict[str, int]:
    """Gives other doctors the same weekly hours (replacing theirs)."""
    await _doctor_or_404(session, doctor_id)
    targets = set(body.doctor_ids) - {doctor_id}
    found = set(await session.scalars(select(Doctor.id).where(Doctor.id.in_(targets))))
    if found != targets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="doctor_not_found")
    rows = list(
        await session.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
    )
    await session.execute(delete(DoctorSchedule).where(DoctorSchedule.doctor_id.in_(targets)))
    for target in targets:
        for r in rows:
            session.add(
                DoctorSchedule(
                    doctor_id=target, branch_id=r.branch_id, weekday=r.weekday,
                    start_time=r.start_time, end_time=r.end_time,
                )
            )  # fmt: skip
    audit.record(
        session, "schedule.copy", user_id=user.id, entity="doctor", entity_id=doctor_id,
        after={"to": sorted(str(t) for t in targets), "rows": len(rows)}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return {"doctors": len(targets), "rows": len(rows)}


class WindowOut(BaseModel):
    starts_at: datetime
    ends_at: datetime


class DoctorDayOut(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    color: str | None
    windows: list[WindowOut]


class ScheduleDayOut(BaseModel):
    date: date
    doctors: list[DoctorDayOut]


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
    return await _day_columns(session, day, branch_id, booked)


@router.get("/schedule/range")
async def schedule_range(
    session: SessionDep,
    _: ScheduleReader,
    date_from: date,
    branch_id: uuid.UUID,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
) -> list[ScheduleDayOut]:
    """The week view: who works at the branch on each day, with their hours."""
    booked: dict[date, set[uuid.UUID]] = defaultdict(set)
    for a in await service.range_appointments(session, date_from, days, branch_id=branch_id):
        booked[a.starts_at.astimezone(service.tz()).date()].add(a.doctor_id)
    out = []
    for offset in range(days):
        day = date_from + timedelta(days=offset)
        out.append(
            ScheduleDayOut(
                date=day, doctors=await _day_columns(session, day, branch_id, booked[day])
            )
        )
    return out


async def _day_columns(
    session: SessionDep, day: date, branch_id: uuid.UUID, booked: set[uuid.UUID]
) -> list[DoctorDayOut]:
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


@router.get("/appointments/range")
async def appointments_range(
    session: SessionDep,
    user: ScheduleReader,
    date_from: date,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
) -> list[AppointmentOut]:
    """Several days at once (week views). A doctor gets only their own visits."""
    if user.role is Role.DOCTOR:
        doctor_id = (await _own_doctor(session, user)).id
    rows = await service.range_appointments(session, date_from, days, branch_id, doctor_id)
    return await serialize(session, rows)


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


@router.post("/appointments/{appointment_id}/resource")
async def set_resource(
    appointment_id: uuid.UUID,
    body: ResourceIn,
    request: Request,
    session: SessionDep,
    user: Booker,
) -> AppointmentOut:
    """Room / device of a visit (TZ 4.3 "kabinet/apparat")."""
    appointment = await _appointment(session, appointment_id)
    before = str(appointment.resource_id) if appointment.resource_id else None
    try:
        await service.assign_resource(session, appointment, body.resource_id)
    except service.SchedulingError as exc:
        raise _err(exc) from None
    audit.record(
        session, "appointment.resource", user_id=user.id, entity="appointment",
        entity_id=appointment.id, before={"resource_id": before},
        after=body.model_dump(mode="json"), ip=client_ip(request),
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
    return (await _recommendations_out(session, user, [rec]))[0]


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
    return await _recommendations_out(session, user, list(rows))


async def _editable_recommendation(
    session: SessionDep, user: User, recommendation_id: uuid.UUID
) -> Recommendation:
    rec = await session.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recommendation_not_found")
    if not await _can_edit_recommendation(session, user, rec):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    return rec


async def _can_edit_recommendation(session: SessionDep, user: User, rec: Recommendation) -> bool:
    if user.role in (Role.REGISTRAR, Role.SUPERVISOR, Role.ADMIN):
        return True
    if user.role is Role.DOCTOR:  # a doctor changes only what they recommended themselves
        doctor = await _doctor_of(session, user)
        return rec.created_by == user.id or bool(doctor and rec.doctor_id == doctor.id)
    return False


@router.patch("/recommendations/{recommendation_id}")
async def update_recommendation(
    recommendation_id: uuid.UUID,
    body: RecommendationUpdate,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> RecommendationOut:
    rec = await _editable_recommendation(session, user, recommendation_id)
    # due_date can't be cleared; service and note can (explicit null)
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k == "due_date" and v is None)
    }
    before = {k: getattr(rec, k) for k in changes}
    try:
        await service.update_recommendation(session, rec, changes=changes)
    except service.SchedulingError as exc:
        raise _err(exc) from None
    audit.record(
        session, "recommendation.update", user_id=user.id, entity="patient",
        entity_id=rec.patient_id,
        before={k: str(v) if v is not None else None for k, v in before.items()},
        after={"id": str(rec.id), **body.model_dump(mode="json", exclude_unset=True)},
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await _recommendations_out(session, user, [rec]))[0]


@router.post("/recommendations/{recommendation_id}/dismiss")
async def dismiss_recommendation(
    recommendation_id: uuid.UUID, request: Request, session: SessionDep, user: CurrentUser
) -> RecommendationOut:
    rec = await _editable_recommendation(session, user, recommendation_id)
    try:
        await service.dismiss_recommendation(session, rec)
    except service.SchedulingError as exc:
        raise _err(exc) from None
    audit.record(
        session, "recommendation.dismiss", user_id=user.id, entity="patient",
        entity_id=rec.patient_id, after={"id": str(rec.id)}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await _recommendations_out(session, user, [rec]))[0]


async def _recommendations_out(
    session: SessionDep, user: User, recs: list[Recommendation]
) -> list[RecommendationOut]:
    if not recs:
        return []
    doctors = dict(
        (
            await session.execute(
                select(Doctor.id, Doctor.name_uz).where(
                    Doctor.id.in_({r.doctor_id for r in recs if r.doctor_id})
                )
            )
        ).all()
    )
    services = {
        s.id: s
        for s in await session.scalars(
            select(Service).where(Service.id.in_({r.service_id for r in recs if r.service_id}))
        )
    }
    out = []
    for r in recs:
        svc = services.get(r.service_id) if r.service_id else None
        editable = r.status is RecommendationStatus.OPEN and await _can_edit_recommendation(
            session, user, r
        )
        out.append(
            RecommendationOut.model_validate(r).model_copy(
                update={
                    "doctor_name": doctors.get(r.doctor_id),
                    "service_name_uz": svc.name_uz if svc else None,
                    "service_name_ru": svc.name_ru if svc else None,
                    "can_edit": editable,
                }
            )
        )
    return out


# --- patient context for the doctor's day --------------------------------------------------------

CONTEXT_VISITS = 10
_CATEGORIES = {c.code: c for c in CATEGORIES}


@router.get("/patient-context/{patient_id}")
async def patient_context(
    patient_id: uuid.UUID, request: Request, session: SessionDep, user: ScheduleReader
) -> PatientContextOut:
    """Diagnosis categories, recent visits, recommendations and notes of one patient."""
    await _check_patient_scope(session, user, patient_id)
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    conditions = await session.scalars(
        select(PatientCondition)
        .where(PatientCondition.patient_id == patient_id)
        .order_by(PatientCondition.created_at.desc())
    )
    visits = await session.scalars(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status.not_in((AppointmentStatus.RESCHEDULED,)),
        )
        .order_by(Appointment.starts_at.desc())
        .limit(CONTEXT_VISITS)
    )
    recs = await session.scalars(
        select(Recommendation)
        .where(Recommendation.patient_id == patient_id)
        .order_by(Recommendation.created_at.desc())
    )
    out = PatientContextOut(
        patient=ContextPatient.model_validate(patient),
        conditions=[
            ContextCondition(
                raw_text=c.raw_text,
                category_code=c.category_code,
                category_name_uz=cat.name_uz if (cat := _CATEGORIES.get(c.category_code)) else None,
                category_name_ru=cat.name_ru if cat else None,
                visit_type=c.visit_type,
            )
            for c in conditions
        ],
        visits=await serialize(session, list(visits)),
        recommendations=await _recommendations_out(session, user, list(recs)),
    )
    # TZ 5: looking at a patient's history is audited like opening the card
    audit.record(
        session, "patient.context", user_id=user.id, entity="patient", entity_id=patient_id,
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return out
