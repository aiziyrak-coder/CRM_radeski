import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.campaigns import service
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.patients.models import Gender, PatientKind, Source
from app.modules.users.models import Role, User

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
Manager = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


class Segment(BaseModel):
    kinds: list[PatientKind] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, max_length=40)
    districts: list[str] = Field(default_factory=list, max_length=40)
    sources: list[Source] = Field(default_factory=list)
    gender: Gender | None = None
    last_visit_before_days: int | None = Field(default=None, ge=1, le=3650)
    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)

    def as_filter(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    segment: Segment
    script_code: str | None = Field(default=None, max_length=30)
    script_code_b: str | None = Field(default=None, max_length=30)
    daily_limit: int = Field(default=30, ge=1, le=500)
    ends_on: datetime | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
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


async def to_out(session: SessionDep, c: Campaign) -> CampaignOut:
    return CampaignOut(
        id=c.id, name=c.name, segment=c.segment, script_code=c.script_code,
        script_code_b=c.script_code_b, daily_limit=c.daily_limit, status=c.status,
        ends_on=c.ends_on, created_at=c.created_at,
        audience=await service.segment_size(session, c.segment),
        stats=await service.stats(session, c.id), ab=await service.ab_stats(session, c),
    )  # fmt: skip


@router.post("/preview")
async def preview(body: Segment, session: SessionDep, _: Manager) -> dict[str, int]:
    return {"audience": await service.segment_size(session, body.as_filter())}


@router.get("")
async def list_campaigns(session: SessionDep, _: Manager) -> list[CampaignOut]:
    rows = await session.scalars(select(Campaign).order_by(Campaign.created_at.desc()))
    return [await to_out(session, c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignIn, request: Request, session: SessionDep, user: Manager
) -> CampaignOut:
    # stored explicitly, so the A/B stats name the script actually used for variant A
    script_a = body.script_code or service.DEFAULT_SCRIPT
    if body.script_code_b and body.script_code_b == script_a:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="same_script")
    campaign = Campaign(
        name=body.name, segment=body.segment.as_filter(), script_code=script_a,
        script_code_b=body.script_code_b or None,
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


class StatusIn(BaseModel):
    status: CampaignStatus


@router.post("/{campaign_id}/status")
async def set_status(
    campaign_id: uuid.UUID, body: StatusIn, request: Request, session: SessionDep, user: Manager
) -> CampaignOut:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign_not_found")
    try:
        await service.set_status(session, campaign, body.status)
    except service.CampaignError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    audit.record(
        session, "campaign.status", user_id=user.id, entity="campaign", entity_id=campaign.id,
        after={"status": body.status.value}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return await to_out(session, campaign)
