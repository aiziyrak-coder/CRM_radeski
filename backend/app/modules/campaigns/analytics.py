"""Campaign figures (TZ 4.9): who is in a segment, which segments to call first, how a campaign
is going (calls, dial rate, bookings, visits, refusal reasons) and who is in it."""

import math
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, case, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.campaigns.service import _UNUSED, segment_query, segment_size
from app.modules.diagnoses.categories import CATEGORY_BY_CODE
from app.modules.patients.models import Patient, PatientCondition, PatientKind, PatientPhone
from app.modules.scheduling.models import Appointment, AppointmentStatus
from app.modules.tasks.models import REACHED, Outcome, Task, TaskAttempt, TaskStatus

VISITED = (AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED)
NOT_BOOKED = (AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED)
TOP = 12  # rows per breakdown; the rest is summed up as "other"


# --- audience ---------------------------------------------------------------------------------


def _rows(counted: list[tuple[Any, int]], total: int) -> list[dict[str, Any]]:
    """Top rows by count; the tail (and rows without a value) as one "other" row."""
    ranked = sorted(((k, n) for k, n in counted if k is not None), key=lambda r: -r[1])
    out = [{"key": str(k), "count": n} for k, n in ranked[:TOP]]
    rest = total - sum(r["count"] for r in out)
    if rest > 0:
        out.append({"key": None, "count": rest})
    return out


async def audience_breakdown(session: AsyncSession, segment: dict[str, Any]) -> dict[str, Any]:
    """Segment size and its make-up, so the supervisor sees who they are about to call."""
    ids = select(segment_query(segment).subquery().c.id)
    total = await segment_size(session, segment)
    in_segment = Patient.id.in_(ids)

    async def by(column) -> list[tuple[Any, int]]:
        return list(
            (
                await session.execute(
                    select(column, func.count()).where(in_segment).group_by(column)
                )
            ).all()
        )

    categories = list(
        (
            await session.execute(
                select(
                    PatientCondition.category_code,
                    func.count(distinct(PatientCondition.patient_id)),
                )
                .where(
                    PatientCondition.patient_id.in_(ids),
                    PatientCondition.category_code.is_not(None),
                )
                .group_by(PatientCondition.category_code)
            )
        ).all()
    )
    days = get_settings().reactivation_after_days
    now = clinic_time.now()
    recency = case(
        (Patient.last_visit_at.is_(None), "never"),
        (Patient.last_visit_at >= now - timedelta(days=days), "recent"),
        (Patient.last_visit_at >= now - timedelta(days=365), "stale"),
        else_="year",
    )
    # categories overlap (one patient can have two), so no "other" row there
    ranked = sorted(categories, key=lambda r: -r[1])[:TOP]
    return {
        "audience": total,
        "by_kind": _rows([(k.value, n) for k, n in await by(Patient.kind)], total),
        "by_district": _rows(await by(Patient.district), total),
        "by_source": _rows(
            [(s.value if s else None, n) for s, n in await by(Patient.source)], total
        ),
        "by_category": [{"key": k, "count": n} for k, n in ranked],
        "by_recency": _rows(await by(recency), total),
    }


# --- suggested segments (TZ 4.9 capacity: the most promising first) --------------------------


async def suggestions(session: AsyncSession) -> list[dict[str, Any]]:
    """Segments worth calling first, with their sizes. One operator makes ~30-50 campaign calls
    a day, so old patients by diagnosis come first and the cold base last."""
    s = get_settings()
    days = s.reactivation_after_days
    old = {"kinds": [PatientKind.LEGACY.value, PatientKind.ACTIVE.value]}
    stale = {**old, "last_visit_before_days": days}
    out: list[dict[str, Any]] = []

    excimer = [
        c.strip() for c in s.campaign_excimer_categories.split(",") if c.strip() in CATEGORY_BY_CODE
    ]
    if excimer:
        out.append(
            {"code": "excimer", "priority": 1, "script_code": "reactivation",
             "categories": excimer, "segment": {**old, "categories": excimer}}
        )  # fmt: skip

    # the largest diagnosis groups of patients not seen for a while -> their specialist
    stale_ids = select(segment_query(stale).subquery().c.id)
    top = (
        await session.execute(
            select(
                PatientCondition.category_code,
                func.count(distinct(PatientCondition.patient_id)).label("n"),
            )
            .where(
                PatientCondition.patient_id.in_(stale_ids),
                PatientCondition.category_code.is_not(None),
                PatientCondition.category_code.not_in(excimer or [""]),
                PatientCondition.category_code != "checkup",
            )
            .group_by(PatientCondition.category_code)
            .order_by(func.count(distinct(PatientCondition.patient_id)).desc())
            .limit(s.campaign_suggest_categories)
        )
    ).all()
    for code, _ in top:
        cat = CATEGORY_BY_CODE.get(code)
        out.append(
            {"code": f"category:{code}", "priority": 2, "script_code": "reactivation",
             "categories": [code], "specialty": cat.specialty.value if cat else None,
             "segment": {**stale, "categories": [code]}}
        )  # fmt: skip

    out += [
        {"code": "reactivation", "priority": 3, "script_code": "reactivation",
         "segment": {"kinds": [PatientKind.ACTIVE.value], "last_visit_before_days": days}},
        {"code": "legacy", "priority": 4, "script_code": "reactivation",
         "segment": {"kinds": [PatientKind.LEGACY.value], "last_visit_before_days": days}},
        {"code": "leads", "priority": 5, "script_code": "thinking",
         "segment": {"kinds": [PatientKind.LEAD.value]}},
        {"code": "cold", "priority": 9, "script_code": "reactivation",
         "segment": {"kinds": [PatientKind.COLD.value]}},
    ]  # fmt: skip

    running = list(
        await session.execute(
            select(Campaign.name, Campaign.segment).where(
                Campaign.status != CampaignStatus.FINISHED
            )
        )
    )
    result = []
    for item in out:
        item["audience"] = await segment_size(session, item["segment"])
        if not item["audience"]:
            continue
        item["days"] = days
        item["campaign"] = next((name for name, seg in running if seg == item["segment"]), None)
        result.append(item)
    return result


# --- results ----------------------------------------------------------------------------------


def _used(campaign_id: uuid.UUID):
    return and_(Task.campaign_id == campaign_id, ~_UNUSED)


def _booked_after_task(statuses=None):
    """An appointment made within the attribution window after the patient's campaign call."""
    window = timedelta(days=get_settings().campaign_attribution_days)
    conds = [
        Appointment.patient_id == Task.patient_id,
        Appointment.created_at >= Task.created_at,
        Appointment.created_at < Task.created_at + window,
    ]
    if statuses is not None:
        conds.append(Appointment.status.in_(statuses))
    else:
        conds.append(Appointment.status.not_in(NOT_BOOKED))
    return exists().where(*conds)


def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


async def results(session: AsyncSession, campaign: Campaign) -> dict[str, Any]:
    """TZ 4.9 campaign results: calls, dial rate, bookings, visits and refusal reasons.

    - calls: operator call results recorded (not the system closing a task after a booking);
    - dial rate: patients reached / patients called (unique patients, like the KPI in TZ 4.11);
    - booked: patients the operator booked, or who booked within `campaign_attribution_days`
      of their campaign call; arrived: such an appointment took place."""
    used = _used(campaign.id)
    start, _ = clinic_time.day_bounds(clinic_time.today())

    counts: dict[str, int] = {"tasks": 0, "open": 0, "closed": 0}
    outcomes: dict[str, int] = {}
    for status, outcome, n in await session.execute(
        select(Task.status, Task.outcome, func.count())
        .where(used)
        .group_by(Task.status, Task.outcome)
    ):
        counts["tasks"] += n
        counts["open" if status is TaskStatus.OPEN else "closed"] += n
        if status is not TaskStatus.OPEN and outcome:
            outcomes[outcome.value] = outcomes.get(outcome.value, 0) + n

    calls = (
        select(
            func.count(),
            func.count(distinct(TaskAttempt.task_id)),
            func.count(distinct(TaskAttempt.task_id)).filter(TaskAttempt.outcome.in_(REACHED)),
            func.count().filter(TaskAttempt.created_at >= start),
        )
        .join(Task, Task.id == TaskAttempt.task_id)
        .where(Task.campaign_id == campaign.id, TaskAttempt.automatic.is_(False))
    )
    n_calls, called, reached, calls_today = (await session.execute(calls)).one()

    async def patients(cond) -> int:
        return (
            await session.scalar(
                select(func.count(distinct(Task.patient_id))).where(
                    used, Task.patient_id.is_not(None), cond
                )
            )
            or 0
        )

    # the operator's "booked" result, or a booking made later (e.g. the patient called back)
    booked = await patients(or_(Task.outcome == Outcome.BOOKED, _booked_after_task()))
    arrived = await patients(_booked_after_task(VISITED))
    reasons: dict[str, int] = {}
    for reason, n in await session.execute(
        select(Task.outcome_reason, func.count())
        .where(used, Task.outcome == Outcome.REFUSED)
        .group_by(Task.outcome_reason)
    ):
        reasons[reason or "other"] = reasons.get(reason or "other", 0) + n
    created_today = (
        await session.scalar(
            select(func.count()).select_from(Task).where(used, Task.created_at >= start)
        )
        or 0
    )
    return {
        **counts,
        "calls": n_calls,
        "called": called,
        "reached": reached,
        "dial_rate": _rate(reached, called),
        "booked": booked,
        "booking_rate": _rate(booked, reached),
        "arrived": arrived,
        "arrival_rate": _rate(arrived, booked),
        "outcomes": outcomes,
        "refusal_reasons": reasons,
        "today": {"tasks": created_today, "calls": calls_today},
    }


async def progress(session: AsyncSession, campaign: Campaign) -> dict[str, Any]:
    """How much of the segment is done and how long the rest takes at the daily limit."""
    already = exists().where(
        Task.patient_id == Patient.id, Task.campaign_id == campaign.id, ~_UNUSED
    )
    remaining = (
        await session.scalar(
            select(func.count()).select_from(
                segment_query(campaign.segment).where(~already).subquery()
            )
        )
        or 0
    )
    tasked = (
        await session.scalar(
            select(func.count(distinct(Task.patient_id))).where(_used(campaign.id))
        )
        or 0
    )
    finished = campaign.status is CampaignStatus.FINISHED
    return {
        "audience": tasked + remaining,
        "tasked": tasked,
        "remaining": remaining,
        "percent": _rate(tasked, tasked + remaining) or 0.0,
        "days_left": None
        if finished or not remaining
        else math.ceil(remaining / max(campaign.daily_limit, 1)),
    }


async def members(
    session: AsyncSession,
    campaign: Campaign,
    *,
    status: TaskStatus | None = None,
    outcome: Outcome | None = None,
    variant: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """The campaign's calls, one row per patient task (newest first), with the result."""
    filters = [_used(campaign.id)]
    if status:
        filters.append(Task.status == status)
    if outcome:
        filters.append(Task.outcome == outcome)
    if variant and campaign.script_code_b:
        b = Task.script_code == campaign.script_code_b
        filters.append(b if variant == "b" else ~b)
    phone = (
        select(PatientPhone.number)
        .where(PatientPhone.patient_id == Task.patient_id)
        .order_by(PatientPhone.is_primary.desc(), PatientPhone.created_at)
        .limit(1)
        .scalar_subquery()
    )
    total = await session.scalar(select(func.count()).select_from(Task).where(*filters)) or 0
    rows = await session.execute(
        select(
            Task,
            Patient.full_name,
            phone.label("phone"),
            or_(Task.outcome == Outcome.BOOKED, _booked_after_task()).label("booked"),
            _booked_after_task(VISITED).label("arrived"),
        )
        .outerjoin(Patient, Patient.id == Task.patient_id)
        .where(*filters)
        .order_by(func.coalesce(Task.completed_at, Task.created_at).desc(), Task.id)
        .limit(limit)
        .offset(offset)
    )
    items = [
        {
            "task_id": t.id,
            "patient_id": t.patient_id,
            "patient_name": name,
            "phone": ph,
            "status": t.status,
            "outcome": t.outcome,
            "reason": t.outcome_reason,
            "attempts": t.attempts,
            "variant": "b"
            if campaign.script_code_b and t.script_code == campaign.script_code_b
            else "a",
            "created_at": t.created_at,
            "last_attempt_at": t.last_attempt_at,
            "completed_at": t.completed_at,
            "booked": bool(booked),
            "arrived": bool(arrived),
        }
        for t, name, ph, booked, arrived in rows
    ]
    return {"total": total, "items": items}
