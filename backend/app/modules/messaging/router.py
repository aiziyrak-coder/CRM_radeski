import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, require_roles
from app.integrations import instagram, openai_client
from app.integrations.llm import LlmError
from app.integrations.sms import get_sms_sender
from app.integrations.telegram import get_telegram
from app.modules.messaging import channels, service
from app.modules.messaging.drafts import draft_reply
from app.modules.messaging.models import (
    Channel,
    Conversation,
    Direction,
    Message,
    MessageStatus,
    MessageTemplate,
)
from app.modules.messaging.rules import appointment_values
from app.modules.patients.models import Patient
from app.modules.scheduling.models import ACTIVE_STATUSES, Appointment
from app.modules.users.models import Role, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/messaging", tags=["messaging"])
webhook_router = APIRouter(prefix="/integrations", tags=["integrations"])

INBOX = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN)
Agent = Annotated[User, Depends(require_roles(*INBOX))]
Editor = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


def _enqueue(message_id: uuid.UUID) -> None:
    from app.workers.celery_app import celery_app

    try:
        celery_app.send_task("jobs.deliver_message", args=[str(message_id)])
    except Exception:  # the per-minute job picks it up anyway
        log.warning("could not queue message %s", message_id)


@router.get("/status")
async def channels_status(_: Agent) -> dict[str, Any]:
    sms = get_sms_sender()
    return {
        "telegram": get_telegram() is not None,
        "instagram": instagram.get_instagram() is not None,
        "sms": sms.name if sms else None,
        "ai": openai_client.enabled(),
    }


# --- inbox ------------------------------------------------------------------------------------


class ConversationOut(BaseModel):
    id: uuid.UUID
    channel: Channel
    title: str | None
    phone: str | None
    patient_id: uuid.UUID | None
    patient_name: str | None
    lead_id: uuid.UUID | None
    last_message_at: datetime | None
    unread: int
    last_text: str | None = None
    last_direction: Direction | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: Direction
    text: str
    status: MessageStatus
    template_code: str | None
    ai_draft: bool
    sent_by_name: str | None = None
    error: str | None
    created_at: datetime
    sent_at: datetime | None


async def _conversation_out(session: SessionDep, rows: list[Conversation]) -> list[ConversationOut]:
    names = dict(
        (
            await session.execute(
                select(Patient.id, Patient.full_name).where(
                    Patient.id.in_({c.patient_id for c in rows if c.patient_id})
                )
            )
        ).all()
    )
    last = {}
    if rows:
        latest = (
            select(Message.conversation_id, func.max(Message.created_at).label("at"))
            .where(Message.conversation_id.in_([c.id for c in rows]))
            .group_by(Message.conversation_id)
            .subquery()
        )
        for m in await session.scalars(
            select(Message).join(
                latest,
                (Message.conversation_id == latest.c.conversation_id)
                & (Message.created_at == latest.c.at),
            )
        ):
            last[m.conversation_id] = m
    return [
        ConversationOut(
            **{f: getattr(c, f) for f in ConversationOut.model_fields if hasattr(c, f)},
            patient_name=names.get(c.patient_id),
            last_text=last[c.id].text[:200] if c.id in last else None,
            last_direction=last[c.id].direction if c.id in last else None,
        )
        for c in rows
    ]


@router.get("/conversations")
async def conversations(
    session: SessionDep,
    _: Agent,
    channel: Channel | None = None,
    unread: bool = False,
    limit: int = Query(default=100, le=300),
) -> list[ConversationOut]:
    stmt = select(Conversation).order_by(Conversation.last_message_at.desc().nulls_last())
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if unread:
        stmt = stmt.where(Conversation.unread > 0)
    return await _conversation_out(session, list(await session.scalars(stmt.limit(limit))))


@router.get("/unread")
async def unread_count(session: SessionDep, _: Agent) -> dict[str, int]:
    n = await session.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.unread > 0)
    )
    return {"conversations": n or 0}


async def _conv_or_404(session: SessionDep, conversation_id: uuid.UUID) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    return conv


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: uuid.UUID, session: SessionDep, _: Agent) -> dict[str, Any]:
    conv = await _conv_or_404(session, conversation_id)
    conv.unread = 0  # opened = read
    rows = await session.execute(
        select(Message, User.full_name)
        .outerjoin(User, User.id == Message.sent_by)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(500)
    )
    messages = [
        MessageOut(
            **{f: getattr(m, f) for f in MessageOut.model_fields if hasattr(m, f)},
            sent_by_name=name,
        )
        for m, name in rows
    ]
    [out] = await _conversation_out(session, [conv])
    await session.commit()
    return {"conversation": out, "messages": messages}


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    template_code: str | None = Field(default=None, max_length=40)
    ai_draft: bool = False


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send(
    conversation_id: uuid.UUID, body: SendIn, session: SessionDep, user: Agent
) -> MessageOut:
    conv = await _conv_or_404(session, conversation_id)
    msg = await service.queue(
        session, conv, body.text.strip(), user_id=user.id, template_code=body.template_code,
        ai_draft=body.ai_draft,
    )  # fmt: skip
    await session.commit()
    _enqueue(msg.id)
    return MessageOut(
        **{f: getattr(msg, f) for f in MessageOut.model_fields if hasattr(msg, f)},
        sent_by_name=user.full_name,
    )


@router.post("/conversations/{conversation_id}/draft")
async def ai_draft(conversation_id: uuid.UUID, session: SessionDep, _: Agent) -> dict[str, str]:
    if not openai_client.enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_disabled")
    if not await openai_client.available():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="ai_budget_exceeded")
    conv = await _conv_or_404(session, conversation_id)
    try:
        return {"text": await draft_reply(session, conv)}
    except LlmError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ai_failed") from exc


class RenderIn(BaseModel):
    code: str = Field(max_length=40)
    language: Literal["uz", "ru"] | None = None


@router.post("/conversations/{conversation_id}/render")
async def render_template(
    conversation_id: uuid.UUID, body: RenderIn, session: SessionDep, _: Agent
) -> dict[str, str]:
    """A template filled with the patient's next appointment and the clinic's phone."""
    conv = await _conv_or_404(session, conversation_id)
    patient = await session.get(Patient, conv.patient_id) if conv.patient_id else None
    lang = body.language or (patient.language.value if patient else "uz")
    values: dict[str, Any] = {}
    if patient:
        from sqlalchemy.orm import selectinload

        appt = await session.scalar(
            select(Appointment)
            .where(
                Appointment.patient_id == patient.id,
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.starts_at >= clinic_time.now(),
            )
            .options(selectinload(Appointment.services))
            .order_by(Appointment.starts_at)
            .limit(1)
        )
        if appt:
            values = await appointment_values(session, appt, lang)
    if "telefon" not in values:
        from app.modules.catalog.models import Branch

        main = await session.scalar(select(Branch).where(Branch.is_main).limit(1))
        values["telefon"] = main.phone if main else ""
    text = await service.render(session, body.code, lang, values)
    if text is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    return {"text": text}


class LinkIn(BaseModel):
    patient_id: uuid.UUID


@router.put("/conversations/{conversation_id}/patient")
async def link_patient(
    conversation_id: uuid.UUID, body: LinkIn, session: SessionDep, _: Agent
) -> ConversationOut:
    conv = await _conv_or_404(session, conversation_id)
    if await session.get(Patient, body.patient_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    await service.link_patient(session, conv, body.patient_id)
    await session.commit()
    [out] = await _conversation_out(session, [conv])
    return out


@router.post("/patients/{patient_id}/sms")
async def open_sms(patient_id: uuid.UUID, session: SessionDep, _: Agent) -> ConversationOut:
    """The SMS thread with a patient (created on first use)."""
    if get_sms_sender() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="sms_off")
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    conv = await service.patient_conversation(session, patient)
    if conv is None or conv.channel is not Channel.SMS:
        from app.modules.patients.models import PatientPhone

        phone = await session.scalar(
            select(PatientPhone.number)
            .where(PatientPhone.patient_id == patient.id)
            .order_by(PatientPhone.is_primary.desc())
            .limit(1)
        )
        if not phone:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="no_phone")
        number = service.e164(phone)
        if not number:  # a foreign / mistyped number: the SMS provider would reject every message
            raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_phone")
        conv = await service.get_conversation(session, Channel.SMS, number, title=patient.full_name)
        conv.patient_id = patient.id
    await session.commit()
    [out] = await _conversation_out(session, [conv])
    return out


# --- templates --------------------------------------------------------------------------------


class TemplateOut(BaseModel):
    id: uuid.UUID
    code: str
    language: str
    title: str
    text: str
    active: bool


class TemplateIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    text: str = Field(min_length=5, max_length=1000)
    active: bool


@router.get("/templates")
async def templates(session: SessionDep, _: Agent) -> list[TemplateOut]:
    await service.seed_templates(session)
    await session.commit()
    rows = await session.scalars(
        select(MessageTemplate).order_by(MessageTemplate.code, MessageTemplate.language)
    )
    return [TemplateOut.model_validate(t, from_attributes=True) for t in rows]


@router.put("/templates/{template_id}")
async def update_template(
    template_id: uuid.UUID, body: TemplateIn, session: SessionDep, user: Editor
) -> TemplateOut:
    tpl = await session.get(MessageTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    tpl.title, tpl.text, tpl.active, tpl.updated_by = body.title, body.text, body.active, user.id
    await session.commit()
    return TemplateOut.model_validate(tpl, from_attributes=True)


# --- webhooks ---------------------------------------------------------------------------------


@webhook_router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    session: SessionDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, Any]:
    expected = get_settings().telegram_webhook_secret
    if not expected or not secret or not hmac.compare_digest(expected, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad_secret")
    try:
        update = json.loads(await request.body())
    except ValueError:
        return {"ok": True}
    reply = await channels.telegram_update(session, update)
    await session.commit()
    return reply or {"ok": True}


@webhook_router.get("/instagram/webhook", include_in_schema=False)
async def instagram_verify(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    expected = get_settings().instagram_verify_token
    if mode == "subscribe" and expected and token and hmac.compare_digest(expected, token):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="bad_token")


@webhook_router.post("/instagram/webhook", include_in_schema=False)
async def instagram_webhook(
    request: Request,
    session: SessionDep,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, int]:
    body = await request.body()
    if not instagram.valid_signature(body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad_signature")
    handled = await channels.instagram_event(
        session, json.loads(body), get_settings().instagram_user_id
    )
    await session.commit()
    return {"handled": handled}


DELIVERED = {"DELIVRD", "DELIVERED", "delivered"}
FAILED = {"UNDELIV", "EXPIRED", "REJECTD", "FAILED", "failed"}


@webhook_router.post("/sms/eskiz/{token}", include_in_schema=False)
async def eskiz_status(token: str, request: Request, session: SessionDep) -> dict[str, bool]:
    """Delivery reports. The secret in the URL (set by us in every send) proves they come from
    Eskiz; only the status of an SMS we sent is flipped."""
    expected = get_settings().eskiz_callback_secret
    if not expected or not hmac.compare_digest(expected.encode(), token.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad_secret")
    try:
        data = await request.json()
    except ValueError:
        data = dict(await request.form())
    ids = {str(data.get(k)) for k in ("message_id", "request_id", "id") if data.get(k)}
    report = str(data.get("status", ""))
    if not ids or report not in DELIVERED | FAILED:
        return {"ok": False}
    msg = await session.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.channel == Channel.SMS,
            Message.direction == Direction.OUT,
            Message.external_id.in_(ids),
            Message.status == MessageStatus.SENT,
        )
        .limit(1)
    )
    if msg:
        msg.status = MessageStatus.DELIVERED if report in DELIVERED else MessageStatus.FAILED
        if msg.status is MessageStatus.FAILED:
            msg.error = f"eskiz: {report}"
        await session.commit()
    return {"ok": msg is not None}
