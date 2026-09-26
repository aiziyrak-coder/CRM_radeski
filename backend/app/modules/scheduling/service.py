"""Schedules, appointments and the free-slot finder (TZ 4.3, ARXITEKTURA 4.4)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import emit
from app.modules.catalog.models import (
    Doctor,
    DoctorService,
    Resource,
    ResourceKind,
    Service,
    ServiceCategory,
)
from app.modules.patients.models import Patient, PatientKind, Source
from app.modules.scheduling.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentService,
    AppointmentStatus,
    DoctorAbsence,
    DoctorSchedule,
)

SLOT_STEP = timedelta(minutes=15)
# don't offer a time that starts in less than this
BOOKING_LEAD = timedelta(minutes=15)

S = AppointmentStatus
TRANSITIONS: dict[AppointmentStatus, set[AppointmentStatus]] = {
    S.SCHEDULED: {S.CONFIRMED, S.ARRIVED, S.NO_SHOW, S.CANCELLED},
    S.CONFIRMED: {S.SCHEDULED, S.ARRIVED, S.NO_SHOW, S.CANCELLED},
    S.ARRIVED: {S.COMPLETED, S.CONFIRMED},  # back to confirmed = "marked by mistake"
    S.NO_SHOW: {S.ARRIVED, S.SCHEDULED},  # came late / marked by mistake
    S.COMPLETED: {S.ARRIVED},
    S.CANCELLED: set(),
    S.RESCHEDULED: set(),
}
PART_OF_DAY = {
    "morning": (time(0), time(12)),
    "afternoon": (time(12), time(16)),
    "evening": (time(16), time(23, 59)),
}


class SchedulingError(Exception):
    """Carries an error code the API returns as `detail`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().tz)


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tz())
    return start, start + timedelta(days=1)


@dataclass
class Slot:
    starts_at: datetime
    ends_at: datetime
    doctor_id: uuid.UUID
    resource_id: uuid.UUID | None


# --- lookups ----------------------------------------------------------------------------------


async def load_services(session: AsyncSession, ids: list[uuid.UUID]) -> list[Service]:
    services = {s.id: s for s in await session.scalars(select(Service).where(Service.id.in_(ids)))}
    missing = [i for i in ids if i not in services or not services[i].is_active]
    if missing or not ids:
        raise SchedulingError("service_not_found")
    return [services[i] for i in ids]  # keep the caller's order


def total_duration(services: list[Service]) -> timedelta:
    return timedelta(minutes=sum(s.duration_min for s in services))


def required_device(services: list[Service]) -> str | None:
    devices = {s.device_type for s in services if s.device_type}
    if len(devices) > 1:
        raise SchedulingError("multiple_devices")
    return devices.pop() if devices else None


async def eligible_doctors(
    session: AsyncSession, services: list[Service], doctor_id: uuid.UUID | None = None
) -> list[Doctor]:
    """Explicit doctor<->service links win; otherwise match by the category's specialty."""
    stmt = select(Doctor).where(Doctor.is_active.is_(True))
    if doctor_id:
        stmt = stmt.where(Doctor.id == doctor_id)
    doctors = list(await session.scalars(stmt.order_by(Doctor.sort_order, Doctor.name_uz)))
    for service in services:
        linked = set(
            await session.scalars(
                select(DoctorService.doctor_id).where(DoctorService.service_id == service.id)
            )
        )
        if linked:
            doctors = [d for d in doctors if d.id in linked]
            continue
        specialty = await _service_specialty(session, service)
        if specialty:
            doctors = [d for d in doctors if specialty in (d.specialties or [])]
    return doctors


async def _service_specialty(session: AsyncSession, service: Service) -> str | None:
    if not service.category_id:
        return None
    category = await session.get(ServiceCategory, service.category_id)
    return category.specialty if category else None


async def working_windows(
    session: AsyncSession, doctor: Doctor, branch_id: uuid.UUID, day: date
) -> list[tuple[datetime, datetime]]:
    absent = await session.scalar(
        select(DoctorAbsence.id).where(
            DoctorAbsence.doctor_id == doctor.id,
            DoctorAbsence.date_from <= day,
            DoctorAbsence.date_to >= day,
        )
    )
    if absent:
        return []
    rows = await session.scalars(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor.id,
            DoctorSchedule.branch_id == branch_id,
            DoctorSchedule.weekday == day.weekday(),
        )
    )
    zone = tz()
    return sorted(
        (datetime.combine(day, r.start_time, zone), datetime.combine(day, r.end_time, zone))
        for r in rows
    )


async def _busy(
    session: AsyncSession, column, ids: list[uuid.UUID], start: datetime, end: datetime
) -> dict[uuid.UUID, list[tuple[datetime, datetime]]]:
    busy: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {i: [] for i in ids}
    if not ids:
        return busy
    rows = await session.execute(
        select(column, Appointment.starts_at, Appointment.ends_at).where(
            column.in_(ids),
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.starts_at < end,
            Appointment.ends_at > start,
        )
    )
    for key, s, e in rows:
        busy[key].append((s, e))
    return busy


def _overlaps(busy: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    return any(s < end and start < e for s, e in busy)


async def _devices(session: AsyncSession, branch_id: uuid.UUID, device_type: str) -> list[Resource]:
    return list(
        await session.scalars(
            select(Resource).where(
                Resource.branch_id == branch_id,
                Resource.kind == ResourceKind.DEVICE,
                Resource.device_type == device_type,
                Resource.is_active.is_(True),
            )
        )
    )


async def earliest_by_course(
    session: AsyncSession, patient_id: uuid.UUID | None, services: list[Service]
) -> date | None:
    """A course procedure can't be repeated before min_interval_days since the last session."""
    if not patient_id:
        return None
    earliest: date | None = None
    for service in services:
        if not service.min_interval_days:
            continue
        last = await session.scalar(
            select(Appointment.starts_at)
            .join(AppointmentService, AppointmentService.appointment_id == Appointment.id)
            .where(
                Appointment.patient_id == patient_id,
                AppointmentService.service_id == service.id,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .order_by(Appointment.starts_at.desc())
            .limit(1)
        )
        if last:
            candidate = last.astimezone(tz()).date() + timedelta(days=service.min_interval_days)
            earliest = max(earliest, candidate) if earliest else candidate
    return earliest


# --- slot finder ------------------------------------------------------------------------------


async def find_slots(
    session: AsyncSession,
    *,
    service_ids: list[uuid.UUID],
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    date_from: date | None = None,
    days: int = 14,
    part_of_day: str | None = None,
    limit: int = 3,
    now: datetime | None = None,
) -> list[Slot]:
    services = await load_services(session, service_ids)
    duration = total_duration(services)
    device = required_device(services)
    doctors = await eligible_doctors(session, services, doctor_id)
    if not doctors:
        return []

    now = now or datetime.now(UTC)
    first_day = max(date_from or now.astimezone(tz()).date(), now.astimezone(tz()).date())
    if (course := await earliest_by_course(session, patient_id, services)) and course > first_day:
        first_day = course
    horizon_start, _ = local_day_bounds(first_day)
    horizon_end = horizon_start + timedelta(days=days)

    devices = await _devices(session, branch_id, device) if device else []
    if device and not devices:
        raise SchedulingError("no_device")
    doctor_busy = await _busy(
        session, Appointment.doctor_id, [d.id for d in doctors], horizon_start, horizon_end
    )
    device_busy = await _busy(
        session, Appointment.resource_id, [r.id for r in devices], horizon_start, horizon_end
    )

    slots: list[Slot] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        day_slots: list[Slot] = []
        for doctor in doctors:
            for w_start, w_end in await working_windows(session, doctor, branch_id, day):
                start = w_start
                while start + duration <= w_end:
                    end = start + duration
                    if (
                        start >= now + BOOKING_LEAD
                        and _in_part(start, part_of_day)
                        and not _overlaps(doctor_busy[doctor.id], start, end)
                    ):
                        resource = next(
                            (r.id for r in devices if not _overlaps(device_busy[r.id], start, end)),
                            None,
                        )
                        if not device or resource:
                            day_slots.append(Slot(start, end, doctor.id, resource))
                    start += SLOT_STEP
        day_slots.sort(key=lambda s: s.starts_at)
        # offer distinct times: one doctor per start time is enough for the operator
        for slot in day_slots:
            if all(s.starts_at != slot.starts_at for s in slots):
                slots.append(slot)
            if len(slots) >= limit:
                return slots
    return slots


def _in_part(start: datetime, part: str | None) -> bool:
    if not part:
        return True
    lo, hi = PART_OF_DAY[part]
    local = start.astimezone(tz()).time()
    return lo <= local < hi


# --- booking ----------------------------------------------------------------------------------


async def create_appointment(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID,
    service_ids: list[uuid.UUID],
    starts_at: datetime,
    source: Source | None,
    note: str | None,
    created_by: uuid.UUID | None,
    allow_outside_hours: bool = False,
    rescheduled_from: Appointment | None = None,
) -> Appointment:
    patient = await session.get(Patient, patient_id)
    if patient is None or patient.merged_into_id:
        raise SchedulingError("patient_not_found")
    doctor = await session.get(Doctor, doctor_id)
    if doctor is None or not doctor.is_active:
        raise SchedulingError("doctor_not_found")
    services = await load_services(session, service_ids)
    if starts_at.tzinfo is None:
        raise SchedulingError("timezone_required")
    ends_at = starts_at + total_duration(services)

    if not allow_outside_hours:
        day = starts_at.astimezone(tz()).date()
        windows = await working_windows(session, doctor, branch_id, day)
        if not any(ws <= starts_at and ends_at <= we for ws, we in windows):
            raise SchedulingError("outside_schedule")

    resource_id = None
    if device := required_device(services):
        devices = await _devices(session, branch_id, device)
        busy = await _busy(
            session, Appointment.resource_id, [r.id for r in devices], starts_at, ends_at
        )
        resource_id = next((r.id for r in devices if not busy[r.id]), None)
        if resource_id is None:
            raise SchedulingError("device_busy" if devices else "no_device")

    appointment = Appointment(
        patient_id=patient_id,
        branch_id=branch_id,
        doctor_id=doctor_id,
        resource_id=resource_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=AppointmentStatus.SCHEDULED,
        source=source,
        note=note,
        created_by=created_by,
        rescheduled_from_id=rescheduled_from.id if rescheduled_from else None,
        services=[
            AppointmentService(
                service_id=s.id, position=i, duration_min=s.duration_min, price=s.price
            )
            for i, s in enumerate(services)
        ],
    )
    session.add(appointment)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        if "no_doctor_overlap" in str(exc.orig) or "no_resource_overlap" in str(exc.orig):
            raise SchedulingError("slot_taken") from None
        raise
    await emit(session, "appointment.created", appointment=appointment, patient=patient)
    return appointment


async def change_status(
    session: AsyncSession,
    appointment: Appointment,
    new: AppointmentStatus,
    *,
    reason: str | None = None,
) -> None:
    old = appointment.status
    if new not in TRANSITIONS[old]:
        raise SchedulingError("invalid_transition")
    if new is AppointmentStatus.CANCELLED and not reason:
        raise SchedulingError("reason_required")
    if new in (AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED):
        patient = await session.get(Patient, appointment.patient_id)
        if patient:
            patient.kind = PatientKind.ACTIVE
            if not patient.last_visit_at or patient.last_visit_at < appointment.starts_at:
                patient.last_visit_at = appointment.starts_at
    appointment.status = new
    appointment.cancel_reason = (
        reason if new in (S.CANCELLED, S.NO_SHOW) else appointment.cancel_reason
    )
    appointment.status_changed_at = datetime.now(UTC)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # e.g. un-cancelling into a slot someone else took meanwhile
        raise SchedulingError("slot_taken") from None
    await emit(session, "appointment.status_changed", appointment=appointment, old=old, new=new)


async def reschedule(
    session: AsyncSession,
    appointment: Appointment,
    *,
    starts_at: datetime,
    doctor_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    allow_outside_hours: bool = False,
) -> Appointment:
    if appointment.status not in (S.SCHEDULED, S.CONFIRMED, S.NO_SHOW):
        raise SchedulingError("invalid_transition")
    old_status = appointment.status
    # free the old slot first so moving within the same doctor's time works
    appointment.status = S.RESCHEDULED
    appointment.status_changed_at = datetime.now(UTC)
    await session.flush()
    new = await create_appointment(
        session,
        patient_id=appointment.patient_id,
        branch_id=appointment.branch_id,
        doctor_id=doctor_id or appointment.doctor_id,
        service_ids=[s.service_id for s in appointment.services],
        starts_at=starts_at,
        source=appointment.source,
        note=appointment.note,
        created_by=user_id,
        allow_outside_hours=allow_outside_hours,
        rescheduled_from=appointment,
    )
    await emit(
        session,
        "appointment.status_changed",
        appointment=appointment,
        old=old_status,
        new=S.RESCHEDULED,
    )
    return new


async def day_appointments(
    session: AsyncSession,
    day: date,
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    include_inactive: bool = True,
) -> list[Appointment]:
    start, end = local_day_bounds(day)
    stmt = select(Appointment).where(Appointment.starts_at >= start, Appointment.starts_at < end)
    if branch_id:
        stmt = stmt.where(Appointment.branch_id == branch_id)
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if not include_inactive:
        stmt = stmt.where(Appointment.status.in_(ACTIVE_STATUSES))
    return list(await session.scalars(stmt.order_by(Appointment.starts_at)))
