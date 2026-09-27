"""TZ 4.8.3 "Kampaniya natijalari bo'yicha xulosa": an AI write-up of a campaign's results.

Only figures and texts without personal data go to the LLM: counts, reasons, and the operators'
notes / call summaries with phone and document numbers masked. No patient names or numbers.
The answer is cached on the campaign with a fingerprint of the facts it was made from: asking
again before anything changed costs nothing."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai.models import AnalysisStatus, CallAnalysis
from app.modules.ai.prompts import mask_pii
from app.modules.campaigns import analytics, service
from app.modules.campaigns.models import Campaign
from app.modules.diagnoses.categories import CATEGORY_BY_CODE
from app.modules.tasks.models import Task, TaskAttempt
from app.modules.telephony.models import Call

PROMPT_VERSION = "campaign-summary-v1"
SYSTEM = (
    "You analyse the results of an outbound call campaign of Radeski Skin Clinic "
    "(dermatology, trichology, cosmetology; Fergana and Kokand, Uzbekistan). Operators call a "
    "segment of the patient base with a script; dial rate = reached / called patients, booked "
    "and arrived = appointments made after the call. Write for the clinic management in Uzbek "
    "(Latin script): what the numbers say, what worked, what went wrong, what the refusal "
    "reasons and objections mean, which A/B script did better (only if an A/B test ran and the "
    "numbers allow a conclusion) and 3-5 concrete next steps (e.g. change the segment, the "
    "script, the daily limit, the time of calls). Base everything only on the data given; "
    "say so when there is too little data to conclude. Never invent numbers."
)


class CampaignSummaryOut(BaseModel):
    summary: str = Field(description="3-5 sentences, Uzbek (Latin)")
    what_worked: list[str]
    problems: list[str]
    refusal_insights: list[str] = Field(
        description="what the refusal reasons, objections and notes say"
    )
    ab_verdict: str | None = Field(
        description="which script did better and how sure we can be; null without an A/B test"
    )
    recommendations: list[str] = Field(description="3-5 concrete next steps")


class NoResultsError(ValueError):
    """Nobody has been called yet: nothing to summarise."""


def _segment_text(segment: dict[str, Any]) -> dict[str, Any]:
    out = dict(segment)
    if cats := segment.get("categories"):
        out["categories"] = [
            CATEGORY_BY_CODE[c].name_uz if c in CATEGORY_BY_CODE else c for c in cats
        ]
    return out


async def facts(session: AsyncSession, campaign: Campaign) -> dict[str, Any]:
    limit = get_settings().campaign_summary_max_notes
    notes = [
        mask_pii(n)[:300]
        for n in await session.scalars(
            select(TaskAttempt.note)
            .join(Task, Task.id == TaskAttempt.task_id)
            .where(
                Task.campaign_id == campaign.id,
                TaskAttempt.automatic.is_(False),
                TaskAttempt.note.is_not(None),
                TaskAttempt.note != "",
            )
            .order_by(TaskAttempt.created_at.desc())
            .limit(limit)
        )
    ]
    analyses = list(
        await session.scalars(
            select(CallAnalysis)
            .join(Call, Call.id == CallAnalysis.call_id)
            .join(Task, Task.id == Call.task_id)
            .where(Task.campaign_id == campaign.id, CallAnalysis.status == AnalysisStatus.READY)
            .order_by(CallAnalysis.created_at.desc())
            .limit(limit)
        )
    )
    return {
        "campaign": {
            "name": mask_pii(campaign.name),
            "goal": mask_pii(campaign.description or "")[:1000] or None,
            "segment": _segment_text(campaign.segment),
            "daily_limit": campaign.daily_limit,
            "status": campaign.status.value,
            "started": campaign.created_at.date().isoformat() if campaign.created_at else None,
            "ends_on": campaign.ends_on.date().isoformat() if campaign.ends_on else None,
        },
        "progress": await analytics.progress(session, campaign),
        "results": await analytics.results(session, campaign),
        "ab_test": await service.ab_stats(session, campaign),
        "operator_notes": notes,
        "call_summaries": [mask_pii(a.summary)[:400] for a in analyses if a.summary],
        "objections": [mask_pii(o)[:200] for a in analyses for o in a.objections or []][:limit],
    }


def fingerprint(data: dict[str, Any]) -> str:
    # "today" figures change during the day without new results: not part of the fingerprint
    stable = {**data, "results": {k: v for k, v in data["results"].items() if k != "today"}}
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{PROMPT_VERSION}:{raw}".encode()).hexdigest()[:24]


async def summarize(session: AsyncSession, campaign: Campaign) -> tuple[dict[str, Any], bool]:
    """The cached write-up when nothing changed since, otherwise a new one (one LLM request,
    counted against the daily AI budget). Returns (summary, cached)."""
    from app.integrations.llm import get_llm

    data = await facts(session, campaign)
    if not data["results"]["calls"]:
        raise NoResultsError
    key = fingerprint(data)
    cached = campaign.ai_summary or {}
    if cached.get("fingerprint") == key and cached.get("content"):
        return cached, True
    llm = get_llm()
    out = await llm.parse(
        system=SYSTEM,
        user=json.dumps(data, ensure_ascii=False, default=str),
        schema=CampaignSummaryOut,
        cache_key=PROMPT_VERSION,
    )
    campaign.ai_summary = {
        "content": out.model_dump(),
        "model": llm.name,
        "prompt_version": PROMPT_VERSION,
        "fingerprint": key,
    }
    campaign.ai_summary_at = datetime.now(UTC)
    await session.flush()
    return campaign.ai_summary, False
