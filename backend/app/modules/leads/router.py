import hashlib
import hmac
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import and_, func, or_, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, client_ip, require_roles
from app.core.text import InvalidPhoneError, normalize_uz_phone
from app.modules.ai.models import AnalysisStatus, CallAnalysis
from app.modules.audit import service as audit
from app.modules.leads import service
from app.modules.leads.models import (
    FUNNEL,
    OPEN_STAGES,
    Lead,
    LeadChannel,
    LeadStage,
    LeadStageChange,
)
from app.modules.messaging.models import Conversation, Message
from app.modules.patients.models import Source
from app.modules.patients.schemas import PhoneNumber
from app.modules.tasks.models import Task, TaskAttempt
from app.modules.telephony.models import Call, RecordingStatus
from app.modules.users.models import Role, User

router = APIRouter(prefix="/leads", tags=["leads"])
webhook_router = APIRouter(prefix="/integrations", tags=["integrations"])
STAFF = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN)
Staff = Annotated[User, Depends(require_roles(*STAFF))]


class LeadIn(BaseModel):
    phone: PhoneNumber | None = None
    name: str | None = Field(default=None, max_length=255)
    channel: LeadChannel = LeadChannel.MANUAL
    # TZ 4.4: mandatory for every inquiry staff enter by hand (checked in create_lead: a
    # missing value is a 422 "source_required", not a generic validation error)
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


SlaState = Literal["waiting", "overdue", "met", "late", "none"]


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
    # waiting: nobody answered yet, still in time; overdue: nobody answered and the time is up
    # (the row is red); met / late: answered in / after time; none: closed without an answer
    sla_state: SlaState
    first_response_at: datetime | None
    appointment_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class LeadPage(BaseModel):
    total: int
    items: list[LeadOut]
    by_stage: dict[str, int]
    # how many of the filtered inquiries reached each funnel step (TZ 4.4)
    funnel: dict[str, int]


def _sla_state(lead: Lead, now: datetime) -> SlaState:
    if lead.first_response_at is not None:
        return "late" if lead.first_response_at > lead.sla_due_at else "met"
    if lead.stage not in OPEN_STAGES:
        return "none"
    return "overdue" if now > lead.sla_due_at else "waiting"


def to_out(lead: Lead) -> LeadOut:
    now = clinic_time.now()
    breached = (lead.first_response_at or now) > lead.sla_due_at
    return LeadOut(
        id=lead.id, patient_id=lead.patient_id, phone=lead.phone, name=lead.name,
        channel=lead.channel, source=lead.source, interest=lead.interest, stage=lead.stage,
        lost_reason=lead.lost_reason, note=lead.note, sla_due_at=lead.sla_due_at,
        sla_breached=breached, sla_state=_sla_state(lead, now),
        first_response_at=lead.first_response_at, appointment_id=lead.appointment_id,
        created_at=lead.created_at, updated_at=lead.updated_at,
    )  # fmt: skip


def _day(value: date | None) -> date | None:
    if value is not None and not 2000 <= value.year <= 2100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_range")
    return value


@router.get("")
async def list_leads(
    session: SessionDep,
    _: Staff,
    stage: LeadStage | None = None,
    channel: LeadChannel | None = None,
    source: Source | None = None,
    patient_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    since: date | None = None,
    until: date | None = None,
    sla: Literal["overdue"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    now = clinic_time.now()
    # everything but the stage: the stage counts and the funnel are of the same selection
    filters = []
    if channel:
        filters.append(Lead.channel == channel)
    if source:
        filters.append(Lead.source == source)
    if patient_id:
        filters.append(Lead.patient_id == patient_id)
    if since := _day(since):
        filters.append(Lead.created_at >= clinic_time.day_bounds(since)[0])
    if until := _day(until):
        filters.append(Lead.created_at < clinic_time.day_bounds(until)[1])
    if sla == "overdue":
        filters.extend(
            (
                Lead.first_response_at.is_(None),
                Lead.sla_due_at < now,
                Lead.stage.in_(OPEN_STAGES),
            )
        )
    if q and q.strip():
        digits = "".join(ch for ch in q if ch.isdigit())
        conds = [Lead.name.ilike(f"%{q.strip()}%")]
        if len(digits) >= 4:
            conds.append(Lead.phone.contains(digits))
        filters.append(or_(*conds))

    by_stage = dict(
        (
            await session.execute(
                select(Lead.stage, func.count()).where(*filters).group_by(Lead.stage)
            )
        ).all()
    )
    booked = (LeadStage.BOOKED, LeadStage.CONFIRMED, LeadStage.VISITED)
    funnel_row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(
                    or_(
                        Lead.first_response_at.is_not(None),
                        Lead.stage.in_((LeadStage.CONTACTED, *booked)),
                    )
                ),
                func.count().filter(or_(Lead.appointment_id.is_not(None), Lead.stage.in_(booked))),
                func.count().filter(Lead.stage.in_((LeadStage.CONFIRMED, LeadStage.VISITED))),
                func.count().filter(Lead.stage == LeadStage.VISITED),
            ).where(*filters)
        )
    ).one()
    funnel = dict(zip([s.value for s in FUNNEL], funnel_row, strict=True))

    listed = [*filters, Lead.stage == stage] if stage else filters
    total = await session.scalar(select(func.count()).select_from(Lead).where(*listed))
    rows = await session.scalars(
        select(Lead)
        .where(*listed)
        .order_by(Lead.created_at.desc(), Lead.id)
        .limit(limit)
        .offset(offset)
    )
    return LeadPage(
        total=total or 0,
        items=[to_out(x) for x in rows],
        by_stage={str(k): v for k, v in by_stage.items()},
        funnel=funnel,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadIn, request: Request, session: SessionDep, user: Staff) -> LeadOut:
    if not body.phone and not body.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="phone_or_name_required")
    if body.source is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="source_required")
    lead, _ = await service.create_lead(session, **body.model_dump(), created_by=user.id)
    audit.record(
        session, "lead.create", user_id=user.id, entity="lead", entity_id=lead.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return to_out(lead)


# --- lead drawer ------------------------------------------------------------------------------


class StageChangeOut(BaseModel):
    old_stage: LeadStage | None
    new_stage: LeadStage
    reason: str | None
    user_name: str | None
    created_at: datetime


class LeadAttemptOut(BaseModel):
    outcome: str
    reason: str | None
    note: str | None
    user_name: str | None
    automatic: bool
    created_at: datetime


class LeadTaskOut(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    due_at: datetime
    outcome: str | None
    attempts: list[LeadAttemptOut]


class LeadCallOut(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    started_at: datetime
    talk_seconds: int | None
    user_name: str | None
    user_id: uuid.UUID | None
    has_recording: bool
    summary: str | None


class LeadMessageOut(BaseModel):
    channel: str
    direction: str
    text: str
    created_at: datetime


class LeadDetail(LeadOut):
    history: list[StageChangeOut]
    tasks: list[LeadTaskOut]
    calls: list[LeadCallOut]
    messages: list[LeadMessageOut]


async def _get_lead(session: SessionDep, lead_id: uuid.UUID) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="lead_not_found")
    return lead


@router.get("/{lead_id}")
async def lead_detail(lead_id: uuid.UUID, session: SessionDep, _: Staff) -> LeadDetail:
    """Everything about one inquiry for the drawer: stage history, calls, chats, tasks."""
    lead = await _get_lead(session, lead_id)
    history = [
        StageChangeOut(
            old_stage=h.old_stage,
            new_stage=h.new_stage,
            reason=h.reason,
            user_name=name,
            created_at=h.created_at,
        )  # fmt: skip
        for h, name in await session.execute(
            select(LeadStageChange, User.full_name)
            .outerjoin(User, User.id == LeadStageChange.user_id)
            .where(LeadStageChange.lead_id == lead.id)
            .order_by(LeadStageChange.created_at, LeadStageChange.id)
        )
    ]
    tasks = list(
        await session.scalars(
            select(Task).where(Task.lead_id == lead.id).order_by(Task.created_at.desc()).limit(20)
        )
    )
    attempts: dict[uuid.UUID, list[LeadAttemptOut]] = {t.id: [] for t in tasks}
    if tasks:
        for a, name in await session.execute(
            select(TaskAttempt, User.full_name)
            .outerjoin(User, User.id == TaskAttempt.user_id)
            .where(TaskAttempt.task_id.in_(attempts))
            .order_by(TaskAttempt.created_at.desc())
        ):
            attempts[a.task_id].append(
                LeadAttemptOut(
                    outcome=a.outcome.value,
                    reason=a.reason,
                    note=a.note,
                    user_name=name,
                    automatic=a.automatic,
                    created_at=a.created_at,
                )  # fmt: skip
            )
    same_caller = [Call.lead_id == lead.id]
    if lead.phone:
        # calls from the number around the inquiry, also the ones before it was linked
        same_caller.append(
            and_(Call.phone == lead.phone, Call.started_at >= lead.created_at - timedelta(hours=1))
        )
    calls = [
        LeadCallOut(
            id=c.id,
            direction=c.direction.value,
            status=c.status.value,
            started_at=c.started_at,
            talk_seconds=c.talk_seconds,
            user_name=name,
            user_id=c.user_id,
            has_recording=c.recording_status is RecordingStatus.READY,
            summary=summary,
        )  # fmt: skip
        for c, name, summary in await session.execute(
            select(Call, User.full_name, CallAnalysis.summary)
            .outerjoin(User, User.id == Call.user_id)
            .outerjoin(
                CallAnalysis,
                (CallAnalysis.call_id == Call.id) & (CallAnalysis.status == AnalysisStatus.READY),
            )
            .where(or_(*same_caller))
            .order_by(Call.started_at.desc())
            .limit(30)
        )
    ]
    messages = [
        LeadMessageOut(
            channel=channel.value,
            direction=m.direction.value,
            text=m.text[:2000],
            created_at=m.created_at,
        )  # fmt: skip
        for m, channel in await session.execute(
            select(Message, Conversation.channel)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.lead_id == lead.id)
            .order_by(Message.created_at.desc())
            .limit(50)
        )
    ]
    return LeadDetail(
        **to_out(lead).model_dump(),
        history=history,
        tasks=[
            LeadTaskOut(
                id=t.id,
                type=t.type.value,
                status=t.status.value,
                due_at=t.due_at,
                outcome=t.outcome.value if t.outcome else None,
                attempts=attempts[t.id],
            )  # fmt: skip
            for t in tasks
        ],
        calls=calls,
        messages=list(reversed(messages)),
    )


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID, body: LeadUpdate, request: Request, session: SessionDep, user: Staff
) -> LeadOut:
    lead = await _get_lead(session, lead_id)
    changes = body.model_dump(exclude_unset=True)
    if "source" in changes and changes["source"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="source_required")
    before = {k: getattr(lead, k) for k in changes}
    stage, lost_reason = changes.pop("stage", None), changes.pop("lost_reason", None)
    for field, value in changes.items():
        setattr(lead, field, value)
    try:
        if stage is not None:
            await service.change_stage(
                session, lead, stage, lost_reason=lost_reason, user_id=user.id
            )
        elif lost_reason is not None:
            await service.change_stage(
                session, lead, lead.stage, lost_reason=lost_reason, user_id=user.id
            )
    except service.LeadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    audit.record(
        session, "lead.update", user_id=user.id, entity="lead", entity_id=lead.id,
        before={k: getattr(v, "value", v) for k, v in before.items()},
        after=body.model_dump(mode="json", exclude_unset=True), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return to_out(lead)


@router.post("/{lead_id}/patient")
async def lead_patient(lead_id: uuid.UUID, session: SessionDep, user: Staff) -> dict[str, str]:
    """Returns the lead's patient card, creating one if needed (booking requires a patient)."""
    lead = await _get_lead(session, lead_id)
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
    try:
        body = SiteAppointmentIn.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from None
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
