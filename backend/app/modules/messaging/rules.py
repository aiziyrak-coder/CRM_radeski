"""Automatic patient messages (TZ 4.10): booking confirmation, reminder, "couldn't reach you"."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import clinic_time
from app.core.events import on
from app.modules.catalog.models import Branch, Doctor, Service
from app.modules.messaging import service
from app.modules.patients.models import Patient
from app.modules.scheduling.models import Appointment, AppointmentStatus
from app.modules.tasks.models import Outcome, Task


async def appointment_values(session: AsyncSession, appt: Appointment, lang: str) -> dict[str, Any]:
    doctor = await session.get(Doctor, appt.doctor_id)
    branch = await session.get(Branch, appt.branch_id)
    local = clinic_time.local(appt.starts_at)
    service_ids = [s.service_id for s in appt.services]
    services = (
        list(await session.scalars(select(Service).where(Service.id.in_(service_ids))))
        if service_ids
        else []
    )
    prep = " ".join(
        p.strip() for s in services if (p := (s.prep_ru if lang == "ru" else s.prep_uz))
    )
    return {
        "sana": f"{local:%d.%m.%Y}",
        "vaqt": f"{local:%H:%M}",
        "shifokor": (doctor.name_ru if lang == "ru" else doctor.name_uz) if doctor else "",
        "manzil": branch.address_uz if branch else "",
        "telefon": branch.phone if branch else "",
        "tayyorgarlik": f"{prep} " if prep else "",
    }


async def _load(session: AsyncSession, appointment_id) -> Appointment | None:
    return await session.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(selectinload(Appointment.services))
    )


@on("appointment.created")
async def _confirm_booking(session: AsyncSession, p: dict[str, Any]) -> None:
    """Script 2 promises "we'll send you a confirmation"."""
    appt = await _load(session, p["appointment"].id)
    patient: Patient | None = await session.get(Patient, appt.patient_id) if appt else None
    if appt is None or patient is None or appt.starts_at <= clinic_time.now():
        return
    lang = patient.language.value
    await service.notify_patient(
        session, patient, "appointment_confirmed", await appointment_values(session, appt, lang),
        dedupe_key=f"confirm:{appt.id}",
    )  # fmt: skip


@on("task.result")
async def _unreachable(session: AsyncSession, p: dict[str, Any]) -> None:
    """TZ 4.5: after the second unanswered attempt the patient gets script 11 as a message."""
    task: Task = p["task"]
    # unanswered attempts only: a "call me later" in between doesn't count
    if p["outcome"] is not Outcome.NO_ANSWER or task.no_answer_count != 2 or not task.patient_id:
        return
    patient = await session.get(Patient, task.patient_id)
    if patient is None or patient.do_not_call:
        return
    branch = await session.scalar(select(Branch).where(Branch.is_main).limit(1))
    await service.notify_patient(
        session, patient, "unreachable", {"telefon": branch.phone if branch else ""},
        dedupe_key=f"unreachable:{task.id}",
    )  # fmt: skip


async def send_reminders(session: AsyncSession, day: date | None = None) -> int:
    """10:00 — everyone booked for tomorrow gets a reminder (with preparation notes)."""
    day = day or clinic_time.today() + timedelta(days=1)
    start, end = clinic_time.day_bounds(day)
    rows = await session.scalars(
        select(Appointment)
        .where(
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            Appointment.status.in_((AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED)),
        )
        .options(selectinload(Appointment.services))
    )
    sent = 0
    for appt in rows:
        patient = await session.get(Patient, appt.patient_id)
        if patient is None:
            continue
        lang = patient.language.value
        msg = await service.notify_patient(
            session, patient, "appointment_reminder",
            await appointment_values(session, appt, lang), dedupe_key=f"reminder:{appt.id}",
        )  # fmt: skip
        sent += msg is not None
    return sent
