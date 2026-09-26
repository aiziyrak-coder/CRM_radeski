"""Operator daily report and KPIs (TZ 4.11). All figures are computed from source tables."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.modules.leads.models import Lead
from app.modules.scheduling.models import (
    Appointment,
    AppointmentStatus,
    Recommendation,
    RecommendationStatus,
)
from app.modules.tasks.models import REACHED, Outcome, Task, TaskAttempt, TaskType
from app.modules.telephony.models import UNANSWERED_INBOUND, Call, CallDirection, CallStatus
from app.modules.users.models import Role, User

S = AppointmentStatus
# roles whose calls the reports break down per person (the daily report's operator filter)
CALLING_ROLES = (Role.OPERATOR, Role.SUPERVISOR)
# campaign-like calls whose patients count as "returned" once they visit (TZ 4.11)
RETURN_TYPES = (TaskType.CAMPAIGN, TaskType.REACTIVATION)


def _range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return clinic_time.day_bounds(date_from)[0], clinic_time.day_bounds(date_to)[1]


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


async def _count(session: AsyncSession, stmt) -> int:
    return await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


async def call_stats(
    session: AsyncSession, start: datetime, end: datetime, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Telephony figures; all None while the PBX isn't connected (no call was ever logged)."""
    keys = (
        "inbound_calls", "inbound_answered", "inbound_missed", "inbound_answer_rate",
        "callbacks_requested", "avg_wait_sec", "outbound_calls", "outbound_answered",
        "talk_minutes",
    )  # fmt: skip
    if not await session.scalar(select(func.count()).select_from(Call)):
        return dict.fromkeys(keys)
    period = [Call.started_at >= start, Call.started_at < end]
    if user_id:  # an operator's own view: calls they handled
        period.append(Call.user_id == user_id)
    answered = Call.status == CallStatus.ANSWERED
    inbound = Call.direction == CallDirection.IN
    row = (
        await session.execute(
            select(
                func.count().filter(inbound),
                func.count().filter(inbound, answered),
                func.count().filter(inbound, Call.status.in_(UNANSWERED_INBOUND)),
                func.count().filter(inbound, Call.callback_requested),
                func.avg(Call.wait_seconds).filter(inbound, Call.wait_seconds.is_not(None)),
                func.count().filter(~inbound),
                func.count().filter(~inbound, answered),
                func.coalesce(func.sum(Call.talk_seconds), 0),
            ).where(*period)
        )
    ).one()
    total_in, in_answered, missed, callbacks, avg_wait, out, out_answered, talk = row
    return {
        "inbound_calls": total_in,
        "inbound_answered": in_answered,
        "inbound_missed": missed,
        "inbound_answer_rate": _pct(in_answered, total_in),
        "callbacks_requested": callbacks,
        "avg_wait_sec": round(float(avg_wait)) if avg_wait is not None else None,
        "outbound_calls": out,
        "outbound_answered": out_answered,
        "talk_minutes": round(talk / 60),
    }


async def daily(
    session: AsyncSession, day: date, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    start, end = clinic_time.day_bounds(day)
    attempts = select(TaskAttempt).where(
        TaskAttempt.created_at >= start, TaskAttempt.created_at < end
    )
    if user_id:
        attempts = attempts.where(TaskAttempt.user_id == user_id)
    # every result incl. the ones a booking wrote (booking figures) ...
    sub = attempts.subquery()
    # ... and only the operators' own calls (attempts, dial rate, outcomes)
    calls = attempts.where(TaskAttempt.automatic.is_(False)).subquery()

    by_outcome = dict(
        (
            await session.execute(select(calls.c.outcome, func.count()).group_by(calls.c.outcome))
        ).all()
    )
    reasons = dict(
        (
            await session.execute(
                select(calls.c.reason, func.count())
                .where(calls.c.reason.is_not(None))
                .group_by(calls.c.reason)
            )
        ).all()
    )
    campaign = dict(
        (
            await session.execute(
                select(sub.c.outcome, func.count())
                .where(sub.c.task_type.in_((TaskType.CAMPAIGN, TaskType.REACTIVATION)))
                .group_by(sub.c.outcome)
            )
        ).all()
    )
    repeat_bookings = await session.scalar(
        select(func.count())
        .select_from(sub)
        .where(
            sub.c.outcome == Outcome.BOOKED,
            sub.c.task_type.in_((TaskType.REPEAT_VISIT, TaskType.COURSE_CONTINUE)),
        )
    )
    booked = select(Appointment.id).where(
        Appointment.created_at >= start, Appointment.created_at < end
    )
    if user_id:
        booked = booked.where(Appointment.created_by == user_id)
    changed = and_(Appointment.status_changed_at >= start, Appointment.status_changed_at < end)
    no_shows = select(Appointment.id).where(
        Appointment.starts_at >= start, Appointment.starts_at < end, Appointment.status == S.NO_SHOW
    )
    total_attempts = sum(by_outcome.values())
    reached = sum(n for o, n in by_outcome.items() if o in REACHED)
    return {
        "date": day.isoformat(),
        **await call_stats(session, start, end, user_id),
        "outbound_attempts": total_attempts,
        "reached": reached,
        "dial_rate": _pct(reached, total_attempts),
        "new_leads": await _count(
            session, select(Lead.id).where(Lead.created_at >= start, Lead.created_at < end)
        ),
        "booked": await _count(session, booked),
        "repeat_bookings": repeat_bookings or 0,
        "not_booked": by_outcome.get(Outcome.REFUSED, 0) + by_outcome.get(Outcome.THINKING, 0),
        "reasons": {str(k): v for k, v in reasons.items()},
        "cancellations": await _count(
            session, select(Appointment.id).where(changed, Appointment.status == S.CANCELLED)
        ),
        "reschedules": await _count(
            session, select(Appointment.id).where(changed, Appointment.status == S.RESCHEDULED)
        ),
        "no_shows": await _count(session, no_shows),
        "outcomes": {str(k): v for k, v in by_outcome.items()},
        "campaign_outcomes": {str(k): v for k, v in campaign.items()},
    }


async def kpi(session: AsyncSession, date_from: date, date_to: date) -> dict[str, Any]:
    start, end = _range(date_from, date_to)
    now = clinic_time.now()

    leads_in = select(Lead).where(Lead.created_at >= start, Lead.created_at < end).subquery()
    leads_total = await session.scalar(select(func.count()).select_from(leads_in)) or 0
    leads_booked = (
        await session.scalar(
            select(func.count()).select_from(leads_in).where(leads_in.c.appointment_id.is_not(None))
        )
        or 0
    )
    median_seconds = await session.scalar(
        select(
            func.percentile_cont(0.5).within_group(
                func.extract("epoch", leads_in.c.first_response_at - leads_in.c.created_at)
            )
        ).where(leads_in.c.first_response_at.is_not(None))
    )
    breached = (
        await session.scalar(
            select(func.count())
            .select_from(leads_in)
            .where(func.coalesce(leads_in.c.first_response_at, now) > leads_in.c.sla_due_at)
        )
        or 0
    )

    # operators' calls only: results written by a booking (automatic) are not dial attempts
    attempts = (
        select(TaskAttempt)
        .where(
            TaskAttempt.created_at >= start,
            TaskAttempt.created_at < end,
            TaskAttempt.automatic.is_(False),
        )
        .subquery()
    )
    total_attempts = await session.scalar(select(func.count()).select_from(attempts)) or 0
    reached = (
        await session.scalar(
            select(func.count()).select_from(attempts).where(attempts.c.outcome.in_(REACHED))
        )
        or 0
    )

    # TZ 4.11 "Tasdiqlash %": confirmed / the day's appointments. Days up to today only (future
    # visits aren't due for confirmation yet); a rescheduled visit lives on as its new booking.
    _, end_of_today = clinic_time.day_bounds(clinic_time.today())
    # a real confirmation: an operator's "confirmed" call result (a patient who simply walked in
    # closes the confirmation task too, but nobody confirmed anything)
    confirm_task = exists().where(
        Task.appointment_id == Appointment.id,
        Task.type == TaskType.CONFIRM_VISIT,
        TaskAttempt.task_id == Task.id,
        TaskAttempt.outcome == Outcome.CONFIRMED,
        TaskAttempt.automatic.is_(False),
    )
    day_appts = (
        select(
            Appointment.id,
            ((Appointment.status == S.CONFIRMED) | confirm_task).label("confirmed"),
        )
        .where(
            Appointment.starts_at >= start,
            Appointment.starts_at < min(end, end_of_today),
            Appointment.status != S.RESCHEDULED,
        )
        .subquery()
    )
    appts_of_day = await session.scalar(select(func.count()).select_from(day_appts)) or 0
    confirmed = (
        await session.scalar(
            select(func.count()).select_from(day_appts).where(day_appts.c.confirmed)
        )
        or 0
    )

    # TZ 4.11 "Qaytarilgan bemorlar": patients a campaign / reactivation call brought back who
    # actually came (a visit in the period, after the call task was created)
    returned = (
        await session.scalar(
            select(func.count(distinct(Appointment.patient_id))).where(
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                Appointment.status.in_((S.ARRIVED, S.COMPLETED)),
                exists().where(
                    Task.patient_id == Appointment.patient_id,
                    Task.type.in_(RETURN_TYPES),
                    Task.outcome == Outcome.BOOKED,
                    Task.created_at <= Appointment.starts_at,
                ),
            )
        )
        or 0
    )

    past = (
        select(Appointment.status)
        .where(
            Appointment.starts_at >= start,
            Appointment.starts_at < min(end, now),
            Appointment.status.in_((S.SCHEDULED, S.CONFIRMED, S.ARRIVED, S.COMPLETED, S.NO_SHOW)),
        )
        .subquery()
    )
    past_total = await session.scalar(select(func.count()).select_from(past)) or 0
    visited = (
        await session.scalar(
            select(func.count())
            .select_from(past)
            .where(past.c.status.in_((S.ARRIVED, S.COMPLETED)))
        )
        or 0
    )
    no_show = (
        await session.scalar(
            select(func.count()).select_from(past).where(past.c.status == S.NO_SHOW)
        )
        or 0
    )

    recs = (
        select(Recommendation.status)
        .where(Recommendation.due_date >= date_from, Recommendation.due_date <= date_to)
        .subquery()
    )
    recs_total = await session.scalar(select(func.count()).select_from(recs)) or 0
    recs_booked = (
        await session.scalar(
            select(func.count())
            .select_from(recs)
            .where(recs.c.status == RecommendationStatus.BOOKED)
        )
        or 0
    )

    operators = await session.execute(
        select(
            User.id, User.full_name, func.count(attempts.c.id),
            func.count().filter(attempts.c.outcome.in_(REACHED)),
            func.count().filter(attempts.c.outcome == Outcome.BOOKED),
        )
        .join(attempts, attempts.c.user_id == User.id)
        .group_by(User.id, User.full_name)
        .order_by(User.full_name)
    )  # fmt: skip
    bookings_by_user = dict(
        (
            await session.execute(
                select(Appointment.created_by, func.count())
                .where(Appointment.created_at >= start, Appointment.created_at < end)
                .group_by(Appointment.created_by)
            )
        ).all()
    )
    talk_by_user = dict(
        (
            await session.execute(
                select(Call.user_id, func.coalesce(func.sum(Call.talk_seconds), 0))
                .where(Call.started_at >= start, Call.started_at < end, Call.user_id.is_not(None))
                .group_by(Call.user_id)
            )
        ).all()
    )
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        **await call_stats(session, start, end),
        "leads_total": leads_total,
        "lead_to_booking": _pct(leads_booked, leads_total),
        "first_response_median_min": round(median_seconds / 60, 1)
        if median_seconds is not None
        else None,
        "sla_breached": breached,
        "attempts": total_attempts,
        "dial_rate": _pct(reached, total_attempts),
        "confirmation_rate": _pct(confirmed, appts_of_day),
        "booking_to_visit": _pct(visited, past_total),
        "no_show_rate": _pct(no_show, past_total),
        "repeat_rate": _pct(recs_booked, recs_total),
        "returned_patients": returned,
        "operators": [
            {
                "user_id": str(uid),
                "name": name,
                "attempts": n,
                "reached": r,
                "dial_rate": _pct(r, n),
                "booked_by_phone": b,
                "appointments_created": bookings_by_user.get(uid, 0),
                "talk_minutes": round(talk_by_user.get(uid, 0) / 60),
            }
            for uid, name, n, r, b in operators
        ],  # fmt: skip
    }


def kpi_workbook(data: dict[str, Any], labels: dict[str, str]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "KPI"
    ws.append(["Davr / Период", f"{data['from']} — {data['to']}"])
    for key, label in labels.items():
        ws.append([label, data.get(key)])
    ops = wb.create_sheet("Operatorlar")
    ops.append(
        [
            "Operator",
            "Urinishlar",
            "Gaplashildi",
            "Dozvon %",
            "Tel. orqali yozildi",
            "Yaratilgan qabullar",
            "Suhbat, daq",
        ]
    )
    for o in data["operators"]:
        ops.append(
            [
                o["name"],
                o["attempts"],
                o["reached"],
                o["dial_rate"],
                o["booked_by_phone"],
                o["appointments_created"],
                o["talk_minutes"],
            ]
        )
    for sheet in (ws, ops):
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = max(
                12, *(len(str(c.value or "")) + 2 for c in column)
            )
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def operators(session: AsyncSession) -> list[dict[str, Any]]:
    """Active call-center staff, for the report's operator filter."""
    rows = await session.execute(
        select(User.id, User.full_name)
        .where(User.is_active.is_(True), User.role.in_(CALLING_ROLES))
        .order_by(User.full_name)
    )
    return [{"id": str(uid), "full_name": name} for uid, name in rows]
