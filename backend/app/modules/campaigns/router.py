import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.campaigns import analytics, service, summary
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.patients.models import Gender, Patient, PatientKind, Source
from app.modules.tasks.models import Outcome, TaskStatus
from app.modules.users.models import Role, User

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
Manager = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


class Segment(BaseModel):
    kinds: list[PatientKind] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, max_length=40)
    districts: list[str] = Field(default_factory=list, max_length=40)
    sources: list[Source] = Field(default_factory=list)
    tags: list[Annotated[str, Field(max_length=50)]] = Field(default_factory=list, max_length=20)
    gender: Gender | None = None
    last_visit_before_days: int | None = Field(default=None, ge=1, le=3650)
    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)

    def as_filter(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    segment: Segment
    script_code: str | None = Field(default=None, max_length=30)
    script_code_b: str | None = Field(default=None, max_length=30)
    daily_limit: int = Field(default=30, ge=1, le=500)
    ends_on: datetime | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    segment: dict[str, Any]
    script_code: str | None
    script_code_b: str | None
    daily_limit: int
    status: CampaignStatus
    ends_on: datetime | None
    created_at: datetime
    audience: int
    stats: dict[str, int]
    ab: list[dict[str, Any]] | None = None
    progress: dict[str, Any] | None = None
    results: dict[str, Any] | None = None


class CampaignDetail(CampaignOut):
    ai_summary: dict[str, Any] | None = None
    ai_summary_at: datetime | None = None
    ai_summary_stale: bool = False


async def to_out(session: SessionDep, c: Campaign) -> CampaignOut:
    return CampaignOut(
        id=c.id, name=c.name, description=c.description, segment=c.segment,
        script_code=c.script_code, script_code_b=c.script_code_b, daily_limit=c.daily_limit,
        status=c.status, ends_on=c.ends_on, created_at=c.created_at,
        audience=await service.segment_size(session, c.segment),
        stats=await service.stats(session, c.id), ab=await service.ab_stats(session, c),
        progress=await analytics.progress(session, c),
        results=await analytics.results(session, c),
    )  # fmt: skip


async def _get(session: SessionDep, campaign_id: uuid.UUID) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign_not_found")
    return campaign


def _check_scripts(body: CampaignIn) -> str:
    # stored explicitly, so the A/B stats name the script actually used for variant A
    script_a = body.script_code or service.DEFAULT_SCRIPT
    if body.script_code_b and body.script_code_b == script_a:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="same_script")
    return script_a


@router.post("/preview")
async def preview(body: Segment, session: SessionDep, _: Manager) -> dict[str, int]:
    return {"audience": await service.segment_size(session, body.as_filter())}


@router.post("/audience")
async def audience(body: Segment, session: SessionDep, _: Manager) -> dict[str, Any]:
    """Segment size with its make-up by patient kind, district, source, diagnosis and recency."""
    return await analytics.audience_breakdown(session, body.as_filter())


@router.get("/suggestions")
async def suggestions(session: SessionDep, _: Manager) -> list[dict[str, Any]]:
    """TZ 4.9: the most promising segments first (old patients by diagnosis, Excimer), cold
    base last — one operator can make only ~30-50 campaign calls a day."""
    return await analytics.suggestions(session)


@router.get("/tags")
async def tags(session: SessionDep, _: Manager) -> list[dict[str, Any]]:
    """Patient tags in use (for the segment filter), most common first."""
    tag = func.unnest(Patient.tags).label("tag")
    sub = select(tag).where(Patient.merged_into_id.is_(None)).subquery()
    rows = await session.execute(
        select(sub.c.tag, func.count())
        .group_by(sub.c.tag)
        .order_by(func.count().desc(), sub.c.tag)
        .limit(200)
    )
    return [{"tag": t, "count": n} for t, n in rows]


# active campaigns first, then paused, drafts, finished
_STATUS_ORDER = case(
    {st: i for i, st in enumerate((CampaignStatus.ACTIVE, CampaignStatus.PAUSED,
                                  CampaignStatus.DRAFT, CampaignStatus.FINISHED))},
    value=Campaign.status,
)  # fmt: skip


@router.get("")
async def list_campaigns(
    session: SessionDep,
    _: Manager,
    status_: Annotated[CampaignStatus | None, Query(alias="status")] = None,
) -> list[CampaignOut]:
    stmt = select(Campaign).order_by(_STATUS_ORDER, Campaign.created_at.desc())
    if status_:
        stmt = stmt.where(Campaign.status == status_)
    return [await to_out(session, c) for c in await session.scalars(stmt)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignIn, request: Request, session: SessionDep, user: Manager
) -> CampaignOut:
    script_a = _check_scripts(body)
    campaign = Campaign(
        name=body.name, description=body.description or None, segment=body.segment.as_filter(),
        script_code=script_a, script_code_b=body.script_code_b or None,
        daily_limit=body.daily_limit, ends_on=body.ends_on, status=CampaignStatus.DRAFT,
        created_by=user.id,
    )  # fmt: skip
    session.add(campaign)
    await session.flush()
    audit.record(
        session, "campaign.create", user_id=user.id, entity="campaign", entity_id=campaign.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return await to_out(session, campaign)


def _editable(c: Campaign) -> dict[str, Any]:
    return {
        "name": c.name, "description": c.description, "segment": c.segment,
        "script_code": c.script_code, "script_code_b": c.script_code_b,
        "daily_limit": c.daily_limit, "ends_on": c.ends_on.isoformat() if c.ends_on else None,
    }  # fmt: skip


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: uuid.UUID, session: SessionDep, _: Manager) -> CampaignDetail:
    campaign = await _get(session, campaign_id)
    out = await to_out(session, campaign)
    stale = False
    if campaign.ai_summary:
        stale = campaign.ai_summary.get("fingerprint") != summary.fingerprint(
            await summary.facts(session, campaign)
        )
    return CampaignDetail(
        **out.model_dump(),
        ai_summary=(campaign.ai_summary or {}).get("content"),
        ai_summary_at=campaign.ai_summary_at,
        ai_summary_stale=stale,
    )


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignIn, request: Request, session: SessionDep, user: Manager
) -> CampaignOut:
    """Edits apply from the next generated calls on; calls already made stay as they are.
    The A/B split is by patient id, so changing script B later keeps each patient's variant."""
    campaign = await _get(session, campaign_id)
    if campaign.status is CampaignStatus.FINISHED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="campaign_finished")
    script_a = _check_scripts(body)
    before = _editable(campaign)
    campaign.name = body.name
    campaign.description = body.description or None
    campaign.segment = body.segment.as_filter()
    campaign.script_code = script_a
    campaign.script_code_b = body.script_code_b or None
    campaign.daily_limit = body.daily_limit
    campaign.ends_on = body.ends_on
    after = _editable(campaign)
    audit.record(
        session, "campaign.update", user_id=user.id, entity="campaign", entity_id=campaign.id,
        before={k: v for k, v in before.items() if after[k] != v},
        after={k: v for k, v in after.items() if before[k] != v}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return await to_out(session, campaign)


class StatusIn(BaseModel):
    status: CampaignStatus


@router.post("/{campaign_id}/status")
async def set_status(
    campaign_id: uuid.UUID, body: StatusIn, request: Request, session: SessionDep, user: Manager
) -> CampaignOut:
    campaign = await _get(session, campaign_id)
    before = campaign.status
    try:
        await service.set_status(session, campaign, body.status)
    except service.CampaignError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    audit.record(
        session, "campaign.status", user_id=user.id, entity="campaign", entity_id=campaign.id,
        before={"status": before.value}, after={"status": body.status.value},
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return await to_out(session, campaign)


class MemberOut(BaseModel):
    task_id: uuid.UUID
    patient_id: uuid.UUID | None
    patient_name: str | None
    phone: str | None
    status: TaskStatus
    outcome: Outcome | None
    reason: str | None
    attempts: int
    variant: Literal["a", "b"]
    created_at: datetime
    last_attempt_at: datetime | None
    completed_at: datetime | None
    booked: bool
    arrived: bool


class MemberPage(BaseModel):
    total: int
    items: list[MemberOut]


@router.get("/{campaign_id}/members")
async def members(
    campaign_id: uuid.UUID,
    session: SessionDep,
    _: Manager,
    status_: Annotated[TaskStatus | None, Query(alias="status")] = None,
    outcome: Outcome | None = None,
    variant: Literal["a", "b"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemberPage:
    campaign = await _get(session, campaign_id)
    page = await analytics.members(
        session, campaign, status=status_, outcome=outcome, variant=variant,
        limit=limit, offset=offset,
    )  # fmt: skip
    return MemberPage.model_validate(page)


@router.post("/{campaign_id}/ai-summary")
async def ai_summary(
    campaign_id: uuid.UUID, request: Request, session: SessionDep, user: Manager
) -> dict[str, Any]:
    """TZ 4.8.3: the AI conclusion on the campaign's results (cached until the results change)."""
    from app.integrations.llm import LlmError
    from app.integrations.openai_client import available, enabled

    campaign = await _get(session, campaign_id)
    if not enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_disabled")
    try:  # an unchanged campaign gets its cached summary, even with today's budget used up
        result, cached = await summary.summarize(session, campaign)
    except summary.NoResultsError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no_results") from None
    except LlmError as exc:
        budget = not await available()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS if budget else status.HTTP_502_BAD_GATEWAY,
            detail="ai_budget_exceeded" if budget else "ai_failed",
        ) from exc
    if not cached:
        audit.record(
            session, "campaign.ai_summary", user_id=user.id, entity="campaign",
            entity_id=campaign.id, after={"model": result.get("model")}, ip=client_ip(request),
        )  # fmt: skip
        await session.commit()
    return {
        "content": result["content"],
        "model": result.get("model"),
        "cached": cached,
        "created_at": campaign.ai_summary_at,
    }
