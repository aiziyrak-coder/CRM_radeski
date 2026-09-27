"""TZ 4.5 rules: domain events and scheduled generators that fill the operator's queue.

Every generator is idempotent (dedupe keys), so beat jobs can safely re-run.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.core.events import on
from app.modules.catalog.models import Service
from app.modules.leads import service as leads
from app.modules.leads.models import OPEN_STAGES, Lead, LeadChannel, LeadStage
from app.modules.patients.models import Patient, PatientKind, PatientPhone
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
    OUTBOUND_TYPES,
    Outcome,
    Task,
    TaskAttempt,
    TaskStatus,
    TaskType,
)
from app.modules.telephony.models import UNANSWERED_INBOUND, Call, CallDirection, CallStatus

S = AppointmentStatus
CONFIRM_TYPES = (TaskType.CONFIRM_VISIT,)
CALL_NOW_TYPES = (TaskType.NEW_LEAD, TaskType.MISSED_CALL, TaskType.CALLBACK, TaskType.LOST_LEAD)
# calls about an inquiry itself: pointless once it is lost or booked
LEAD_TASK_TYPES = (TaskType.NEW_LEAD, TaskType.MISSED_CALL, TaskType.LOST_LEAD)
BOOKED_AHEAD = (S.SCHEDULED, S.CONFIRMED)


async def _has_future_visit(
    session: AsyncSession,
    patient_id: uuid.UUID,
    *,
    exclude: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
) -> bool:
    """The patient is already booked (for this service), so there is nobody to call."""
    stmt = select(Appointment.id).where(
        Appointment.patient_id == patient_id,
        Appointment.starts_at > clinic_time.now(),
        Appointment.status.in_(BOOKED_AHEAD),
    )
    if exclude:
        stmt = stmt.where(Appointment.id != exclude)
    if service_id:
        stmt = stmt.where(
            exists().where(
                AppointmentService.appointment_id == Appointment.id,
                AppointmentService.service_id == service_id,
            )
        )
    return await session.scalar(stmt.limit(1)) is not None


async def close_already_booked(session: AsyncSession) -> int:
    """TZ 4.5 #6, #8: a repeat-visit or course call isn't made when that visit is already booked.

    Checked when the call comes due, not when it is created: a booking that is cancelled or
    missed later then still leaves the patient with a call."""
    soon = clinic_time.now() + timedelta(days=1)
    due = await session.scalars(
        select(Task).where(
            Task.status == TaskStatus.OPEN,
            Task.type.in_((TaskType.REPEAT_VISIT, TaskType.COURSE_CONTINUE)),
            Task.due_at <= soon,
            Task.patient_id.is_not(None),
        )
    )
    closed = 0
    for task in list(due):
        services: list[uuid.UUID | None] = [None]
        if task.type is TaskType.REPEAT_VISIT and task.recommendation_id:
            rec = await session.get(Recommendation, task.recommendation_id)
            if rec is not None and rec.service_id:
                services = [rec.service_id]
        elif task.type is TaskType.COURSE_CONTINUE and task.appointment_id:
            services = list(
                await session.scalars(
                    select(AppointmentService.service_id).where(
                        AppointmentService.appointment_id == task.appointment_id
                    )
                )
            ) or [None]
        for service_id in services:
            if await _has_future_visit(
                session, task.patient_id, exclude=task.appointment_id, service_id=service_id
            ):
                task.status, task.outcome = TaskStatus.DONE, Outcome.BOOKED
                task.completed_at = clinic_time.now()
                closed += 1
                break
    await session.flush()
    return closed


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
        # the booking closed the task, not a call: reports don't count it as a dial attempt
        session.add(
            TaskAttempt(
                task_id=t.id, task_type=t.type, user_id=appt.created_by, patient_id=t.patient_id,
                outcome=Outcome.BOOKED, automatic=True, created_at=now,
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
        lead.appointment_id = appt.id
        await leads.change_stage(session, lead, LeadStage.BOOKED, user_id=appt.created_by)


@on("appointment.status_changed")
async def _on_status(session: AsyncSession, p: dict[str, Any]) -> None:
    appt: Appointment = p["appointment"]
    new: AppointmentStatus = p["new"]
    if new in (S.CONFIRMED, S.ARRIVED, S.COMPLETED):
        # a patient who came in without being reached was not "confirmed" (KPI 4.11)
        outcome = Outcome.CONFIRMED if new is S.CONFIRMED else Outcome.DONE
        await tasks.close_open(
            session, types=CONFIRM_TYPES, appointment_id=appt.id, outcome=outcome
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
            await leads.change_stage(session, lead, LeadStage.VISITED)
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
            # TZ 4.5 #8 "only when the next session isn't booked" is checked when the call comes
            # due (close_already_booked): a booking cancelled later must not lose the call
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
    # TZ 4.5 #6 "if the patient hasn't booked yet" is checked when the call comes due
    lead_days = get_settings().repeat_visit_lead_days
    due = max(clinic_time.at(rec.due_date - timedelta(days=lead_days), time(9)), clinic_time.now())
    await tasks.create_task(
        session, TaskType.REPEAT_VISIT, due_at=due, patient_id=rec.patient_id,
        recommendation_id=rec.id, note=rec.note, dedupe_key=f"rec:{rec.id}",
    )  # fmt: skip


@on("recommendation.changed")
async def _on_recommendation_changed(session: AsyncSession, p: dict[str, Any]) -> None:
    """The doctor edited or withdrew a recommendation: its pending call follows."""
    rec: Recommendation = p["recommendation"]
    pending = (Task.recommendation_id == rec.id, Task.status == TaskStatus.OPEN)
    if rec.status is RecommendationStatus.DISMISSED:
        await session.execute(
            update(Task)
            .where(*pending)
            .values(status=TaskStatus.CANCELLED, completed_at=clinic_time.now())
            .execution_options(synchronize_session=False)
        )
        return
    lead_days = get_settings().repeat_visit_lead_days
    due = max(clinic_time.at(rec.due_date - timedelta(days=lead_days), time(9)), clinic_time.now())
    await session.execute(
        update(Task)
        .where(*pending, Task.attempts == 0)  # a call already in progress keeps its retry time
        .values(due_at=due, note=rec.note)
        .execution_options(synchronize_session=False)
    )


@on("lead.created")
async def _on_lead(session: AsyncSession, p: dict[str, Any]) -> None:
    lead: Lead = p["lead"]
    await tasks.create_task(
        session, TaskType.NEW_LEAD, due_at=lead.sla_due_at,
        patient_id=lead.patient_id, lead_id=lead.id, note=lead.interest,
        dedupe_key=f"lead:{lead.id}",
    )  # fmt: skip


@on("lead.stage_changed")
async def _on_lead_stage(session: AsyncSession, p: dict[str, Any]) -> None:
    lead: Lead = p["lead"]
    new: LeadStage = p["new"]
    if new is LeadStage.LOST:
        await tasks.close_open(
            session, types=LEAD_TASK_TYPES, lead_id=lead.id, outcome=None,
            status=TaskStatus.CANCELLED,
        )  # fmt: skip
    elif new is LeadStage.BOOKED:
        await tasks.close_open(
            session, types=LEAD_TASK_TYPES, lead_id=lead.id, outcome=Outcome.BOOKED
        )


@on("patient.do_not_call_set")
async def _on_do_not_call(session: AsyncSession, p: dict[str, Any]) -> None:
    """TZ 4.1: "don't call" set on the card (or kept by a merge) takes the patient out of every
    campaign, reactivation and lost-lead call, as the call result "do_not_call" already does."""
    await tasks.close_open(
        session, types=OUTBOUND_TYPES, patient_id=p["patient"].id,
        outcome=Outcome.DO_NOT_CALL, status=TaskStatus.CANCELLED,
    )  # fmt: skip


@on("call.finished")
async def _on_call(session: AsyncSession, p: dict[str, Any]) -> None:
    call: Call = p["call"]
    if call.direction is not CallDirection.IN:
        return
    if call.status is CallStatus.ANSWERED:
        # the person got through: an earlier missed call (and a fresh inquiry) is resolved
        if call.patient_id:
            await tasks.close_open(
                session, types=(TaskType.MISSED_CALL,), patient_id=call.patient_id,
                outcome=Outcome.DONE,
            )  # fmt: skip
        match = [Lead.id == call.lead_id] if call.lead_id else []
        if call.phone:
            match.append(Lead.phone == call.phone)
        if not match:
            return
        for lead in await session.scalars(
            select(Lead).where(or_(*match), Lead.stage.in_(OPEN_STAGES))
        ):
            leads.mark_contacted(lead)
            if not call.patient_id:
                await tasks.close_open(
                    session, types=(TaskType.MISSED_CALL, TaskType.NEW_LEAD), lead_id=lead.id,
                    outcome=Outcome.DONE,
                )  # fmt: skip
        return
    if call.status not in UNANSWERED_INBOUND or not call.phone:
        return
    # TZ 4.5 #1: every missed call is called back, first thing when the clinic is open
    now = clinic_time.now()
    due = now if clinic_time.is_open(now) else clinic_time.next_opening(now)
    note = "1 ni bosib qayta qo'ng'iroq so'radi" if call.callback_requested else None
    if call.patient_id:
        owner, target = Task.patient_id == call.patient_id, {"patient_id": call.patient_id}
    elif call.lead_id:
        owner, target = Task.lead_id == call.lead_id, {"lead_id": call.lead_id}
    else:
        # an unknown number becomes an inquiry (its "new inquiry" task carries the 15-min SLA)
        lead, _ = await leads.create_lead(
            session, channel=LeadChannel.MISSED_CALL, phone=call.phone,
            note=note or "Javobsiz qo'ng'iroq",
        )  # fmt: skip
        call.lead_id = lead.id
        return
    # calling again while a callback is pending doesn't pile up tasks; once that task is
    # closed, a new missed call gets a new one (the key per call keeps a re-sent event idempotent)
    # an inquiry whose "new inquiry" task is still open is the same callback
    covering = (
        (TaskType.MISSED_CALL, TaskType.NEW_LEAD) if call.lead_id else (TaskType.MISSED_CALL,)
    )
    pending = await session.scalar(
        select(Task)
        .where(owner, Task.type.in_(covering), Task.status == TaskStatus.OPEN)
        .order_by(Task.created_at)
        .limit(1)
    )
    if pending is not None:
        started = clinic_time.local(call.started_at or datetime.now(UTC))
        for line in (f"Yana qo'ng'iroq qildi {started:%H:%M}", note):
            if line and line not in (pending.note or ""):
                pending.note = f"{pending.note}\n{line}" if pending.note else line
        pending.due_at = min(pending.due_at, due)  # they are waiting: not later than a new task
        return
    await tasks.create_task(
        session, TaskType.MISSED_CALL, due_at=due, dedupe_key=f"missed:{call.id}", note=note,
        **target,
    )  # fmt: skip


@on("task.result")
async def _on_task_result(session: AsyncSession, p: dict[str, Any]) -> None:
    task: Task = p["task"]
    outcome: Outcome = p["outcome"]
    if outcome is Outcome.WRONG_NUMBER and task.patient_id:
        # the number that was dialled (the primary one) isn't this person's: no campaign calls it
        # again. The card stays; another number can be added.
        await session.execute(
            update(PatientPhone)
            .where(
                PatientPhone.patient_id == task.patient_id,
                PatientPhone.is_primary.is_(True),
                PatientPhone.wrong_number_at.is_(None),
            )
            .values(wrong_number_at=clinic_time.now())
        )
    if task.lead_id:
        lead = await session.get(Lead, task.lead_id)
        if lead:
            if outcome not in (Outcome.NO_ANSWER, Outcome.WRONG_NUMBER):
                leads.mark_contacted(lead)
            if outcome in (Outcome.REFUSED, Outcome.WRONG_NUMBER, Outcome.DO_NOT_CALL):
                reason = p.get("reason")
                await leads.change_stage(
                    session, lead, LeadStage.LOST,
                    lost_reason=reason if reason in leads.LOST_REASONS else outcome.value,
                    user_id=p.get("user_id"), contacted=outcome is not Outcome.WRONG_NUMBER,
                )  # fmt: skip
            elif outcome is Outcome.THINKING:
                await leads.change_stage(session, lead, LeadStage.LATER, user_id=p.get("user_id"))
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
    cutoff = clinic_time.now() - timedelta(hours=get_settings().lost_lead_after_hours)
    # someone is already due to call this person: the inquiry's own task, or a patient call of
    # the "call now" kinds (a repeat-visit call months ahead doesn't count)
    has_open = exists().where(
        Task.status == TaskStatus.OPEN,
        or_(
            Task.lead_id == Lead.id,
            and_(
                Lead.patient_id.is_not(None),
                Task.patient_id == Lead.patient_id,
                Task.type.in_(CALL_NOW_TYPES),
            ),
        ),
    )
    rows = await session.scalars(
        select(Lead).where(
            Lead.stage.in_((LeadStage.NEW, LeadStage.CONTACTED, LeadStage.LATER)),
            Lead.created_at < cutoff,
            Lead.appointment_id.is_(None),
            ~has_open,
        )
    )
    created = 0
    for lead in rows:
        created += await tasks.create_task(
            session, TaskType.LOST_LEAD, due_at=clinic_time.now(), patient_id=lead.patient_id,
            lead_id=lead.id, note=lead.interest, dedupe_key=f"lost:{lead.id}",
        )  # fmt: skip
    return created


async def generate_reactivation(session: AsyncSession, limit: int | None = None) -> int:
    """Patients who haven't visited for 6 months (TZ 4.5 #9), a few per day."""
    settings = get_settings()
    limit = settings.reactivation_daily_limit if limit is None else limit
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
            Patient.last_visit_at < now - timedelta(days=settings.reactivation_after_days),
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
