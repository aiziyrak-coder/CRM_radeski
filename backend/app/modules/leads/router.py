import hashlib
import hmac
import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, client_ip, require_roles
from app.core.text import InvalidPhoneError, normalize_uz_phone
from app.modules.audit import service as audit
from app.modules.leads import service
from app.modules.leads.models import Lead, LeadChannel, LeadStage
from app.modules.patients.models import Source
from app.modules.patients.schemas import PhoneNumber
from app.modules.users.models import Role, User

router = APIRouter(prefix="/leads", tags=["leads"])
webhook_router = APIRouter(prefix="/integrations", tags=["integrations"])
STAFF = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN)
Staff = Annotated[User, Depends(require_roles(*STAFF))]


class LeadIn(BaseModel):
    phone: PhoneNumber | None = None
    name: str | None = Field(default=None, max_length=255)
    channel: LeadChannel = LeadChannel.MANUAL
    source: Source | None = None
    interest: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    source: Source | None = None
    interest: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    stage: LeadStage | None = None
    lost_reason: str | None = Field(default=None, max_length=50)


class LeadOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID | None
    phone: str | None
    name: str | None
    channel: LeadChannel
    source: Source | None
    interest: str | None
    stage: LeadStage
    lost_reason: str | None
    note: str | None
    sla_due_at: datetime
    sla_breached: bool
    first_response_at: datetime | None
    appointment_id: uuid.UUID | None
    created_at: datetime


class LeadPage(BaseModel):
    total: int
    items: list[LeadOut]
    by_stage: dict[str, int]


def to_out(lead: Lead) -> LeadOut:
    now = clinic_time.now()
    breached = (lead.first_response_at or now) > lead.sla_due_at
    return LeadOut(
        id=lead.id, patient_id=lead.patient_id, phone=lead.phone, name=lead.name,
        channel=lead.channel, source=lead.source, interest=lead.interest, stage=lead.stage,
        lost_reason=lead.lost_reason, note=lead.note, sla_due_at=lead.sla_due_at,
        sla_breached=breached, first_response_at=lead.first_response_at,
        appointment_id=lead.appointment_id, created_at=lead.created_at,
    )  # fmt: skip


@router.get("")
async def list_leads(
    session: SessionDep,
    _: Staff,
    stage: LeadStage | None = None,
    channel: LeadChannel | None = None,
    patient_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    since: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    filters = []
    if stage:
        filters.append(Lead.stage == stage)
    if channel:
        filters.append(Lead.channel == channel)
    if patient_id:
        filters.append(Lead.patient_id == patient_id)
    if since:
        filters.append(Lead.created_at >= clinic_time.day_bounds(since)[0])
    if q and q.strip():
        digits = "".join(ch for ch in q if ch.isdigit())
        conds = [Lead.name.ilike(f"%{q.strip()}%")]
        if len(digits) >= 4:
            conds.append(Lead.phone.contains(digits))
        filters.append(or_(*conds))
    total = await session.scalar(select(func.count()).select_from(Lead).where(*filters))
    by_stage = dict(
        (await session.execute(select(Lead.stage, func.count()).group_by(Lead.stage))).all()
    )
    rows = await session.scalars(
        select(Lead).where(*filters).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    )
    return LeadPage(
        total=total or 0,
        items=[to_out(x) for x in rows],
        by_stage={str(k): v for k, v in by_stage.items()},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadIn, request: Request, session: SessionDep, user: Staff) -> LeadOut:
    if not body.phone and not body.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="phone_or_name_required")
    lead, _ = await service.create_lead(session, **body.model_dump(), created_by=user.id)
    audit.record(
        session, "lead.create", user_id=user.id, entity="lead", entity_id=lead.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return to_out(lead)


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID, body: LeadUpdate, request: Request, session: SessionDep, user: Staff
) -> LeadOut:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="lead_not_found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("stage") is LeadStage.LOST and not (
        changes.get("lost_reason") or lead.lost_reason
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="reason_required")
    for field, value in changes.items():
        setattr(lead, field, value)
    if changes.get("stage") and changes["stage"] is not LeadStage.NEW:
        service.mark_contacted(lead)
    audit.record(
        session, "lead.update", user_id=user.id, entity="lead", entity_id=lead.id,
        after=body.model_dump(mode="json", exclude_unset=True), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return to_out(lead)


@router.post("/{lead_id}/patient")
async def lead_patient(lead_id: uuid.UUID, session: SessionDep, user: Staff) -> dict[str, str]:
    """Returns the lead's patient card, creating one if needed (booking requires a patient)."""
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="lead_not_found")
    patient = await service.ensure_patient(session, lead, user.id)
    await session.commit()
    return {"patient_id": str(patient.id)}


# --- website form webhook (radeski.uz -> CRM) -------------------------------------------------


class SiteAppointmentIn(BaseModel):
    id: str = Field(max_length=100)
    phone_number: str = Field(max_length=40)
    client_name: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=2000)
    preferred_date: date | None = None
    service_name_uz: str | None = Field(default=None, max_length=500)


def _valid_signature(body: bytes, signature: str | None) -> bool:
    secret = get_settings().site_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


@webhook_router.post("/site/appointments", status_code=status.HTTP_202_ACCEPTED)
async def site_appointment(
    request: Request,
    session: SessionDep,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> dict[str, str]:
    """The site's "Qabulga yozilish" form. Signed with HMAC-SHA256 (shared secret)."""
    raw = await request.body()
    if not _valid_signature(raw, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad_signature")
    body = SiteAppointmentIn.model_validate_json(raw)
    lead, created = await intake_site_appointment(session, body)
    await session.commit()
    return {"lead_id": str(lead.id), "status": "created" if created else "duplicate"}


async def intake_site_appointment(
    session: SessionDep, body: SiteAppointmentIn
) -> tuple[Lead, bool]:
    try:
        phone = normalize_uz_phone(body.phone_number)
    except InvalidPhoneError:
        phone = None
    parts = [p for p in (body.service_name_uz, body.comment) if p]
    if body.preferred_date:
        parts.append(f"Qulay sana: {body.preferred_date.isoformat()}")
    return await service.create_lead(
        session,
        channel=LeadChannel.WEBSITE,
        phone=phone,
        name=body.client_name,
        source=Source.WEBSITE,
        interest="; ".join(parts) or None,
        note=None if phone else f"Saytdagi raqam: {body.phone_number}",
        external_id=f"site:{body.id}",
    )
