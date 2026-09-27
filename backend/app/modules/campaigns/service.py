"""Campaign segments and the daily task generator (TZ 4.9)."""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.patients.models import Patient, PatientCondition, PatientPhone
from app.modules.scheduling.models import ACTIVE_STATUSES, Appointment
from app.modules.tasks import service as tasks
from app.modules.tasks.models import (
    REACHED,
    TASK_DEFAULTS,
    Outcome,
    Task,
    TaskStatus,
    TaskType,
)

C = CampaignStatus
# the script a campaign task gets when the campaign names none
DEFAULT_SCRIPT = TASK_DEFAULTS[TaskType.CAMPAIGN][1]
# FINISHED is final; a paused campaign can be resumed
TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    C.DRAFT: {C.ACTIVE, C.FINISHED},
    C.ACTIVE: {C.PAUSED, C.FINISHED},
    C.PAUSED: {C.ACTIVE, C.FINISHED},
    C.FINISHED: set(),
}
# a task the pause/finish cancelled before anyone called: it doesn't use up the patient
# (a resumed campaign may call them) nor the day's limit
_UNUSED = and_(Task.status == TaskStatus.CANCELLED, Task.attempts == 0)


class CampaignError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def segment_query(segment: dict[str, Any]) -> Select:
    """Patient ids matching a segment; do-not-call and merged cards are always excluded."""
    stmt = select(Patient.id).where(
        Patient.merged_into_id.is_(None),
        Patient.do_not_call.is_(False),
        # someone to call: a number that wasn't reported wrong (imports leave some without any)
        exists().where(
            PatientPhone.patient_id == Patient.id, PatientPhone.wrong_number_at.is_(None)
        ),
    )
    if kinds := segment.get("kinds"):
        stmt = stmt.where(Patient.kind.in_(kinds))
    if districts := segment.get("districts"):
        stmt = stmt.where(Patient.district.in_(districts))
    if sources := segment.get("sources"):
        stmt = stmt.where(Patient.source.in_(sources))
    if gender := segment.get("gender"):
        stmt = stmt.where(Patient.gender == gender)
    if categories := segment.get("categories"):
        stmt = stmt.where(
            exists().where(
                PatientCondition.patient_id == Patient.id,
                PatientCondition.category_code.in_(categories),
            )
        )
    if days := segment.get("last_visit_before_days"):
        cutoff = clinic_time.now() - timedelta(days=int(days))
        stmt = stmt.where((Patient.last_visit_at.is_(None)) | (Patient.last_visit_at < cutoff))
    today = clinic_time.today()
    if (age_min := segment.get("age_min")) is not None:
        stmt = stmt.where(Patient.birth_date <= _years_ago(today, int(age_min)))
    if (age_max := segment.get("age_max")) is not None:
        stmt = stmt.where(Patient.birth_date > _years_ago(today, int(age_max) + 1))
    return stmt


def _years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 Feb
        return today.replace(year=today.year - years, day=28)


async def segment_size(session: AsyncSession, segment: dict[str, Any]) -> int:
    return (
        await session.scalar(select(func.count()).select_from(segment_query(segment).subquery()))
        or 0
    )


async def generate_for_campaign(session: AsyncSession, campaign: Campaign) -> int:
    """Adds up to the remaining daily limit; skips patients already called in this campaign,
    patients with any open task and patients with an upcoming appointment."""
    if campaign.status is not CampaignStatus.ACTIVE or _ended(campaign):
        return 0
    now = clinic_time.now()
    start, _ = clinic_time.day_bounds(clinic_time.today())
    created_today = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.campaign_id == campaign.id, Task.created_at >= start, ~_UNUSED)
    )
    remaining = campaign.daily_limit - (created_today or 0)
    if remaining <= 0:
        return 0
    already = exists().where(
        Task.patient_id == Patient.id, Task.campaign_id == campaign.id, ~_UNUSED
    )
    open_task = exists().where(Task.patient_id == Patient.id, Task.status == TaskStatus.OPEN)
    upcoming = exists().where(
        Appointment.patient_id == Patient.id,
        Appointment.starts_at > now,
        Appointment.status.in_(ACTIVE_STATUSES),
    )
    stmt = segment_query(campaign.segment).where(~already, ~open_task, ~upcoming).limit(remaining)
    created = 0
    for pid in list(await session.scalars(stmt)):
        created += await tasks.create_task(
            session, TaskType.CAMPAIGN, due_at=now, patient_id=pid, campaign_id=campaign.id,
            script_code=script_for(campaign, pid), dedupe_key=f"camp:{campaign.id}:{pid}",
        )  # fmt: skip
    return created


def _ended(campaign: Campaign) -> bool:
    return campaign.ends_on is not None and campaign.ends_on < clinic_time.now()


async def cancel_open_tasks(session: AsyncSession, campaign: Campaign) -> int:
    """A paused or finished campaign leaves nothing in the operators' queue."""
    result = await session.execute(
        update(Task)
        .where(Task.campaign_id == campaign.id, Task.status == TaskStatus.OPEN)
        .values(
            status=TaskStatus.CANCELLED,
            completed_at=clinic_time.now(),
            # frees the dedupe key of a never-called task so a resumed campaign can call them
            dedupe_key=case((Task.attempts == 0, None), else_=Task.dedupe_key),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def set_status(session: AsyncSession, campaign: Campaign, new: CampaignStatus) -> None:
    if new is campaign.status:
        return
    if new not in TRANSITIONS[campaign.status]:
        raise CampaignError("invalid_transition")
    if new is C.ACTIVE and _ended(campaign):
        raise CampaignError("campaign_ended")
    campaign.status = new
    if new in (C.PAUSED, C.FINISHED):
        await cancel_open_tasks(session, campaign)
    elif new is C.ACTIVE:
        # start today rather than waiting for tomorrow's morning run
        await generate_for_campaign(session, campaign)


def script_for(campaign: Campaign, patient_id: uuid.UUID) -> str | None:
    """A/B split by patient id: stable (a patient always gets the same variant), ~50/50."""
    if campaign.script_code_b and patient_id.int % 2:
        return campaign.script_code_b
    return campaign.script_code


async def ab_stats(session: AsyncSession, campaign: Campaign) -> list[dict[str, Any]] | None:
    """Per-variant results: which script books more patients (TZ 6: A/B scripts)."""
    if not campaign.script_code_b:
        return None
    rows = await session.execute(
        select(Task.script_code, Task.status, Task.outcome, func.count())
        .where(Task.campaign_id == campaign.id)
        .group_by(Task.script_code, Task.status, Task.outcome)
    )
    by: dict[str | None, dict[str, int]] = {}
    for code, status, outcome, n in rows:
        v = by.setdefault(code, {"tasks": 0, "done": 0, "reached": 0, "booked": 0})
        v["tasks"] += n
        if status is not TaskStatus.OPEN:
            v["done"] += n
        if outcome in REACHED:
            v["reached"] += n
        if outcome is Outcome.BOOKED:
            v["booked"] += n
    out = []
    script_a = campaign.script_code or DEFAULT_SCRIPT  # campaigns created before it was stored
    for variant, code in (("a", script_a), ("b", campaign.script_code_b)):
        v = by.get(code, {"tasks": 0, "done": 0, "reached": 0, "booked": 0})
        rate = round(100 * v["booked"] / v["reached"], 1) if v["reached"] else None
        out.append({"variant": variant, "script_code": code, **v, "booking_rate": rate})
    return out


async def generate_all(session: AsyncSession) -> int:
    total = 0
    for campaign in await session.scalars(
        select(Campaign).where(Campaign.status == CampaignStatus.ACTIVE)
    ):
        if _ended(campaign):
            await set_status(session, campaign, CampaignStatus.FINISHED)
            continue
        total += await generate_for_campaign(session, campaign)
    return total


async def stats(session: AsyncSession, campaign_id) -> dict[str, int]:
    rows = await session.execute(
        select(Task.status, Task.outcome, func.count())
        .where(Task.campaign_id == campaign_id)
        .group_by(Task.status, Task.outcome)
    )
    out: dict[str, int] = {"total": 0, "open": 0}
    for status, outcome, n in rows:
        out["total"] += n
        if status is TaskStatus.OPEN:
            out["open"] += n
        elif outcome:
            out[outcome.value] = out.get(outcome.value, 0) + n
    return out
