"""Campaign segments and the daily task generator (TZ 4.9)."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.patients.models import Patient, PatientCondition
from app.modules.scheduling.models import ACTIVE_STATUSES, Appointment
from app.modules.tasks import service as tasks
from app.modules.tasks.models import Task, TaskStatus, TaskType


def segment_query(segment: dict[str, Any]) -> Select:
    """Patient ids matching a segment; do-not-call and merged cards are always excluded."""
    stmt = select(Patient.id).where(
        Patient.merged_into_id.is_(None), Patient.do_not_call.is_(False)
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
    if campaign.status is not CampaignStatus.ACTIVE:
        return 0
    now = clinic_time.now()
    start, _ = clinic_time.day_bounds(clinic_time.today())
    created_today = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.campaign_id == campaign.id, Task.created_at >= start)
    )
    remaining = campaign.daily_limit - (created_today or 0)
    if remaining <= 0:
        return 0
    already = exists().where(Task.patient_id == Patient.id, Task.campaign_id == campaign.id)
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
            script_code=campaign.script_code, dedupe_key=f"camp:{campaign.id}:{pid}",
        )  # fmt: skip
    return created


async def generate_all(session: AsyncSession) -> int:
    total = 0
    for campaign in await session.scalars(
        select(Campaign).where(Campaign.status == CampaignStatus.ACTIVE)
    ):
        if campaign.ends_on and campaign.ends_on < clinic_time.now():
            campaign.status = CampaignStatus.FINISHED
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
