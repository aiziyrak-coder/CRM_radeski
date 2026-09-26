"""TZ 4.5 rules: domain events and scheduled generators that fill the operator's queue.

Every generator is idempotent (dedupe keys), so beat jobs can safely re-run.
"""

from datetime import date, time, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.events import on
from app.modules.catalog.models import Service
from app.modules.leads import service as leads
from app.modules.leads.models import OPEN_STAGES, Lead, LeadStage
from app.modules.patients.models import Patient, PatientKind
from app.modules.scheduling.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentService,
    AppointmentStatus,
    Recommendation,
    RecommendationStatus,
)
from app.modules.tasks import service as tasks
from app.modules.tasks.models import (
    CLOSED_BY_BOOKING,
    Outcome,
    Task,
    TaskAttempt,
    TaskStatus,
    TaskType,
)

S = AppointmentStatus
CONFIRM_TYPES = (TaskType.CONFIRM_VISIT,)
REPEAT_LEAD_DAYS = 3  # call this many days before the doctor's recommended date
LOST_LEAD_AFTER = timedelta(hours=24)
REACTIVATION_AFTER = timedelta(days=180)  # TZ 4.5: default 6 months
REACTIVATION_DAILY_LIMIT = 20


# --- events -----------------------------------------------------------------------------------


@on("appointment.created")
async def _on_booked(session: AsyncSession, p: dict[str, Any]) -> None:
    appt: Appointment = p["appointment"]
    now = clinic_time.now()
    # anything we were calling this patient about is resolved by the booking
    open_tasks = list(
        await session.scalars(
            select(Task).where(
                Task.patient_id == appt.patient_id,
                Task.status == TaskStatus.OPEN,
                Task.type.in_(CLOSED_BY_BOOKING),
            )
        )
    )
    for t in open_tasks:
        t.status, t.outcome, t.completed_at, t.completed_by = (
            TaskStatus.DONE, Outcome.BOOKED, now, appt.created_by,
        )  # fmt: skip
        t.attempts += 1
        session.add(
            TaskAttempt(
                task_id=t.id, task_type=t.type, user_id=appt.created_by, patient_id=t.patient_id,
                outcome=Outcome.BOOKED, created_at=now,
            )
        )  # fmt: skip
    for rec in await session.scalars(
        select(Recommendation).where(
            Recommendation.patient_id == appt.patient_id,
            Recommendation.status == RecommendationStatus.OPEN,
        )
    ):
        rec.status = RecommendationStatus.BOOKED
    for lead in await session.scalars(
        select(Lead).where(Lead.patient_id == appt.patient_id, Lead.stage.in_(OPEN_STAGES))
    ):
        leads.mark_contacted(lead)
        lead.stage = LeadStage.BOOKED
        lead.appointment_id = appt.id


@on("appointment.status_changed")
async def _on_status(session: AsyncSession, p: dict[str, Any]) -> None:
    appt: Appointment = p["appointment"]
    new: AppointmentStatus = p["new"]
    if new in (S.CONFIRMED, S.ARRIVED, S.COMPLETED):
        await tasks.close_open(
            session, types=CONFIRM_TYPES, appointment_id=appt.id, outcome=Outcome.CONFIRMED
        )
    elif new in (S.CANCELLED, S.RESCHEDULED):
        await tasks.close_open(
            session,
            types=CONFIRM_TYPES,
            appointment_id=appt.id,
            outcome=Outcome.CANCELLED if new is S.CANCELLED else Outcome.RESCHEDULED,
            status=TaskStatus.CANCELLED,
        )
    if new is S.NO_SHOW:
        await tasks.create_task(
            session, TaskType.NO_SHOW, due_at=clinic_time.now(), patient_id=appt.patient_id,
            appointment_id=appt.id, dedupe_key=f"noshow:{appt.id}",
        )  # fmt: skip
    if new is S.ARRIVED:
        for lead in await session.scalars(
            select(Lead).where(Lead.patient_id == appt.patient_id, Lead.stage == LeadStage.BOOKED)
        ):
            lead.stage = LeadStage.VISITED
    if new is S.COMPLETED:
        await _after_procedure(session, appt)


async def _after_procedure(session: AsyncSession, appt: Appointment) -> None:
    visit_day = clinic_time.local(appt.starts_at).date()
    for line in appt.services:
        service = await session.get(Service, line.service_id)
        if service is None:
            continue
        if service.followup_call_days is not None:
            call_day = visit_day + timedelta(days=service.followup_call_days)
            await tasks.create_task(
                session, TaskType.POST_PROCEDURE,
                due_at=clinic_time.at(call_day, time(10)),
                patient_id=appt.patient_id, appointment_id=appt.id,
                dedupe_key=f"post:{appt.id}:{service.id}",
            )  # fmt: skip
        if service.course_sessions and service.min_interval_days:
            done = await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .join(AppointmentService, AppointmentService.appointment_id == Appointment.id)
                .where(
                    Appointment.patient_id == appt.patient_id,
                    AppointmentService.service_id == service.id,
                    Appointment.status == S.COMPLETED,
                )
            )
            if (done or 0) < service.course_sessions:
                due = visit_day + timedelta(days=max(service.min_interval_days - 2, 0))
                await tasks.create_task(
                    session, TaskType.COURSE_CONTINUE, due_at=clinic_time.at(due, time(10)),
                    patient_id=appt.patient_id, appointment_id=appt.id,
                    note=f"{service.name_uz}: {done}/{service.course_sessions}",
                    dedupe_key=f"course:{appt.patient_id}:{service.id}:{done}",
                )  # fmt: skip


@on("recommendation.created")
async def _on_recommendation(session: AsyncSession, p: dict[str, Any]) -> None:
    rec: Recommendation = p["recommendation"]
    due = max(
        clinic_time.at(rec.due_date - timedelta(days=REPEAT_LEAD_DAYS), time(9)), clinic_time.now()
    )
    await tasks.create_task(
        session, TaskType.REPEAT_VISIT, due_at=due, patient_id=rec.patient_id,
        recommendation_id=rec.id, note=rec.note, dedupe_key=f"rec:{rec.id}",
    )  # fmt: skip


@on("lead.created")
async def _on_lead(session: AsyncSession, p: dict[str, Any]) -> None:
    lead: Lead = p["lead"]
    await tasks.create_task(
        session, TaskType.NEW_LEAD, due_at=lead.sla_due_at,
        patient_id=lead.patient_id, lead_id=lead.id, note=lead.interest,
        dedupe_key=f"lead:{lead.id}",
    )  # fmt: skip


@on("task.result")
async def _on_task_result(session: AsyncSession, p: dict[str, Any]) -> None:
    task: Task = p["task"]
    outcome: Outcome = p["outcome"]
    if task.lead_id:
        lead = await session.get(Lead, task.lead_id)
        if lead:
            if outcome not in (Outcome.NO_ANSWER, Outcome.WRONG_NUMBER):
                leads.mark_contacted(lead)
            if outcome in (Outcome.REFUSED, Outcome.WRONG_NUMBER, Outcome.DO_NOT_CALL):
                lead.stage, lead.lost_reason = LeadStage.LOST, p.get("reason") or outcome.value
            elif outcome is Outcome.THINKING:
                lead.stage = LeadStage.LATER
    # confirming by phone updates the appointment itself (no double work for the operator)
    if task.type is TaskType.CONFIRM_VISIT and task.appointment_id:
        from app.modules.scheduling import service as scheduling

        appt = await session.get(Appointment, task.appointment_id)
        if appt and appt.status is S.SCHEDULED:
            if outcome is Outcome.CONFIRMED:
                await scheduling.change_status(session, appt, S.CONFIRMED)
            elif outcome is Outcome.CANCELLED:
                await scheduling.change_status(
                    session, appt, S.CANCELLED, reason=p.get("reason") or "patient_request"
                )


# --- scheduled generators ---------------------------------------------------------------------


async def generate_confirmations(session: AsyncSession, day: date | None = None) -> int:
    """07:30 — call everyone booked for today (TZ 4.5 #1)."""
    day = day or clinic_time.today()
    start, end = clinic_time.day_bounds(day)
    rows = await session.scalars(
        select(Appointment).where(
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            Appointment.status == S.SCHEDULED,
        )
    )
    created = 0
    for appt in rows:
        created += await tasks.create_task(
            session, TaskType.CONFIRM_VISIT, due_at=clinic_time.at(day, time(7, 30)),
            patient_id=appt.patient_id, appointment_id=appt.id, dedupe_key=f"confirm:{appt.id}",
        )  # fmt: skip
    return created


async def generate_lost_leads(session: AsyncSession) -> int:
    """Inquiries that didn't turn into a booking within 24 hours (TZ 4.5 #4)."""
    cutoff = clinic_time.now() - LOST_LEAD_AFTER
    rows = await session.scalars(
        select(Lead).where(
            Lead.stage.in_((LeadStage.NEW, LeadStage.CONTACTED, LeadStage.LATER)),
            Lead.created_at < cutoff,
            Lead.appointment_id.is_(None),
        )
    )
    created = 0
    for lead in rows:
        created += await tasks.create_task(
            session, TaskType.LOST_LEAD, due_at=clinic_time.now(), patient_id=lead.patient_id,
            lead_id=lead.id, note=lead.interest, dedupe_key=f"lost:{lead.id}",
        )  # fmt: skip
    return created


async def generate_reactivation(
    session: AsyncSession, limit: int = REACTIVATION_DAILY_LIMIT
) -> int:
    """Patients who haven't visited for 6 months (TZ 4.5 #9), a few per day."""
    now = clinic_time.now()
    has_future = exists().where(
        Appointment.patient_id == Patient.id,
        Appointment.starts_at > now,
        Appointment.status.in_(ACTIVE_STATUSES),
    )
    has_open = exists().where(Task.patient_id == Patient.id, Task.status == TaskStatus.OPEN)
    rows = await session.scalars(
        select(Patient.id)
        .where(
            Patient.kind == PatientKind.ACTIVE,
            Patient.merged_into_id.is_(None),
            Patient.do_not_call.is_(False),
            Patient.last_visit_at < now - REACTIVATION_AFTER,
            ~has_future,
            ~has_open,
        )
        .order_by(Patient.last_visit_at.desc())
        .limit(limit)
    )
    month = clinic_time.local(now).strftime("%Y-%m")
    created = 0
    for pid in rows:
        created += await tasks.create_task(
            session, TaskType.REACTIVATION, due_at=now, patient_id=pid,
            dedupe_key=f"react:{pid}:{month}",
        )  # fmt: skip
    return created
