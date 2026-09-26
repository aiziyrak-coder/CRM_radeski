"""Shared inbox (TZ 4.4) and template messages / reminders (TZ 4.10)."""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.core.events import emit
from app.core.text import InvalidPhoneError, normalize_uz_phone
from app.integrations.instagram import get_instagram
from app.integrations.sms import SendError, get_sms_sender
from app.integrations.telegram import get_telegram
from app.modules.leads import service as leads
from app.modules.leads.models import OPEN_STAGES, Lead, LeadChannel
from app.modules.messaging.models import (
    Channel,
    Conversation,
    Direction,
    Message,
    MessageStatus,
    MessageTemplate,
)
from app.modules.patients import service as patients_service
from app.modules.patients.models import Patient, PatientPhone

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
LEAD_CHANNEL = {Channel.TELEGRAM: LeadChannel.TELEGRAM, Channel.INSTAGRAM: LeadChannel.INSTAGRAM}

# TZ 4.10: pre-approved texts. {placeholders} are filled from the appointment / clinic.
DEFAULT_TEMPLATES = [
    ("appointment_confirmed", "uz", "Yozuv tasdig'i",
     "Radeski Skin Clinic: siz {sana} kuni soat {vaqt} da {shifokor} qabuliga yozildingiz. "
     "Manzil: {manzil}. Savollar uchun: {telefon}"),
    ("appointment_confirmed", "ru", "Подтверждение записи",
     "Radeski Skin Clinic: вы записаны {sana} в {vaqt} к специалисту {shifokor}. "
     "Адрес: {manzil}. Вопросы: {telefon}"),
    ("appointment_reminder", "uz", "Qabul eslatmasi",
     "Eslatma: ertaga, {sana} soat {vaqt} da {shifokor} qabulingiz bor. {tayyorgarlik}"
     "Radeski Skin Clinic, {telefon}"),
    ("appointment_reminder", "ru", "Напоминание о приёме",
     "Напоминаем: завтра, {sana} в {vaqt} у вас приём ({shifokor}). {tayyorgarlik}"
     "Radeski Skin Clinic, {telefon}"),
    ("unreachable", "uz", "Bog'lana olmadik (11-skript)",
     "Assalomu alaykum! Radeski Skin Clinic sizga qo'ng'iroq qildi, lekin bog'lana olmadik. "
     "Qulay vaqtda {telefon} raqamiga qo'ng'iroq qiling yoki shu xabarga javob yozing."),
    ("unreachable", "ru", "Не дозвонились (скрипт 11)",
     "Здравствуйте! Radeski Skin Clinic звонила вам, но не смогла дозвониться. "
     "Перезвоните, пожалуйста, по номеру {telefon} или ответьте на это сообщение."),
    ("telegram_welcome", "uz", "Telegram: salomlashish",
     "Assalomu alaykum! Radeski Skin Clinic. Savolingizni yozing — operatorimiz tez orada javob "
     "beradi. Qabulga yozilish uchun telefon raqamingizni yuboring (pastdagi tugma)."),
    ("telegram_welcome", "ru", "Telegram: приветствие",
     "Здравствуйте! Radeski Skin Clinic. Напишите ваш вопрос — оператор скоро ответит. "
     "Чтобы записаться, отправьте номер телефона (кнопка ниже)."),
]  # fmt: skip


def telegram_msg_id(message_id: Any, business: str | None) -> str | None:
    """Telegram numbers messages per chat, and a person's chat with the bot and with the
    clinic's Business account share one chat id: keep the two id sequences apart."""
    if message_id is None:
        return None
    return f"b{message_id}" if business else str(message_id)


def e164(raw: str | None) -> str | None:
    try:
        return normalize_uz_phone(raw) if raw else None
    except InvalidPhoneError:
        return None


# --- templates --------------------------------------------------------------------------------


async def seed_templates(session: AsyncSession) -> int:
    if await session.scalar(select(MessageTemplate.id).limit(1)):
        return 0
    for code, language, title, text in DEFAULT_TEMPLATES:
        session.add(MessageTemplate(code=code, language=language, title=title, text=text))
    await session.flush()
    return len(DEFAULT_TEMPLATES)


async def render(
    session: AsyncSession, code: str, language: str, values: dict[str, Any]
) -> str | None:
    await seed_templates(session)
    tpl = await session.scalar(
        select(MessageTemplate).where(
            MessageTemplate.code == code,
            MessageTemplate.language == language,
            MessageTemplate.active,
        )
    )
    if tpl is None:
        return None
    filled = defaultdict(str, {k: v for k, v in values.items() if v is not None})
    return " ".join(tpl.text.format_map(filled).split())


# --- conversations ----------------------------------------------------------------------------


async def get_conversation(
    session: AsyncSession,
    channel: Channel,
    external_id: str,
    *,
    title: str | None = None,
    lock: bool = False,
) -> Conversation:
    """The chat (created on first use). Two webhooks for a new chat at once create it once;
    `lock` holds the row until commit so concurrent messages of one chat are handled in turn."""
    await session.execute(
        insert(Conversation)
        .values(id=uuid.uuid4(), channel=channel, external_id=external_id, title=title, unread=0)
        .on_conflict_do_nothing(index_elements=["channel", "external_id"])
    )
    stmt = select(Conversation).where(
        Conversation.channel == channel, Conversation.external_id == external_id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    conv = (await session.scalars(stmt)).one()
    if title and not conv.title:
        conv.title = title
    return conv


async def link_patient(session: AsyncSession, conv: Conversation, patient_id: uuid.UUID) -> None:
    conv.patient_id = patient_id
    if conv.lead_id and (lead := await session.get(Lead, conv.lead_id)) and not lead.patient_id:
        lead.patient_id = patient_id


async def set_phone(session: AsyncSession, conv: Conversation, raw: str) -> None:
    phone = e164(raw)
    if not phone:
        return
    conv.phone = phone
    if not conv.patient_id and (patient := await leads.find_patient_by_phone(session, phone)):
        await link_patient(session, conv, patient.id)
    if conv.lead_id and (lead := await session.get(Lead, conv.lead_id)) and not lead.phone:
        lead.phone = phone


async def store_message(
    session: AsyncSession,
    conv: Conversation,
    direction: Direction,
    text: str,
    status: MessageStatus,
    external_id: str | None,
    now: datetime,
) -> uuid.UUID | None:
    """A received (or sent-elsewhere) message; None when this provider id is already stored."""
    msg_id = uuid.uuid4()
    stmt = (
        insert(Message)
        .values(
            id=msg_id, conversation_id=conv.id, direction=direction, text=text, status=status,
            external_id=external_id, created_at=now, attempts=0,
            sent_at=now if direction is Direction.OUT else None,
        )
        .on_conflict_do_nothing(
            index_elements=["conversation_id", "direction", "external_id"],
            index_where=Message.external_id.isnot(None),
        )
        .returning(Message.id)
    )  # fmt: skip
    if (await session.execute(stmt)).scalar() is None:
        return None
    conv.last_message_at = now
    return msg_id


async def receive(
    session: AsyncSession,
    channel: Channel,
    external_id: str,
    text: str,
    *,
    title: str | None = None,
    external_msg_id: str | None = None,
    phone: str | None = None,
    business_connection_id: str | None = None,
) -> Message | None:
    """An inbound chat message. A chat without an open inquiry becomes one (-> operator task).

    None = the provider re-delivered a message we already have (webhook retry)."""
    now = clinic_time.now()
    # locked: two messages of one chat arriving together must not open two inquiries
    conv = await get_conversation(session, channel, external_id, title=title, lock=True)
    msg_id = await store_message(
        session, conv, Direction.IN, text, MessageStatus.RECEIVED, external_msg_id, now
    )
    if msg_id is None:
        return None
    msg = await session.get(Message, msg_id)
    if business_connection_id:
        conv.business_connection_id = business_connection_id
    if phone:
        await set_phone(session, conv, phone)
    conv.unread += 1

    lead = await session.get(Lead, conv.lead_id) if conv.lead_id else None
    # a "thank you" right after the inquiry was closed shouldn't open a new one
    recently_closed = lead is not None and lead.updated_at > now - timedelta(hours=24)
    if (lead is None or (lead.stage not in OPEN_STAGES and not recently_closed)) and (
        channel in LEAD_CHANNEL
    ):
        lead, _ = await leads.create_lead(
            session, channel=LEAD_CHANNEL[channel], phone=conv.phone, name=conv.title,
            interest=text[:500],
        )  # fmt: skip
        conv.lead_id = lead.id
        if lead.patient_id and not conv.patient_id:
            conv.patient_id = lead.patient_id
    await session.flush()
    await emit(session, "message.received", message=msg, conversation=conv)
    return msg


def _next_allowed(now: datetime) -> datetime:
    s = get_settings()
    local = clinic_time.local(now)
    if s.messages_from_hour <= local.hour < s.messages_to_hour:
        return now
    day = local.date() if local.hour < s.messages_from_hour else local.date() + timedelta(days=1)
    return clinic_time.at(day, time(s.messages_from_hour))


async def queue(
    session: AsyncSession,
    conv: Conversation,
    text: str,
    *,
    user_id: uuid.UUID | None = None,
    template_code: str | None = None,
    dedupe_key: str | None = None,
    ai_draft: bool = False,
) -> Message | None:
    """Outbound message; automatic ones (no user) wait for the allowed hours. None = duplicate."""
    now = clinic_time.now()
    msg_id = uuid.uuid4()
    stmt = (
        insert(Message)
        .values(
            id=msg_id, conversation_id=conv.id, direction=Direction.OUT, text=text,
            status=MessageStatus.QUEUED, template_code=template_code, ai_draft=ai_draft,
            sent_by=user_id, dedupe_key=dedupe_key, attempts=0, created_at=now,
            send_after=None if user_id else _next_allowed(now),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Message.id)
    )  # fmt: skip
    if (await session.execute(stmt)).scalar() is None:
        return None
    conv.last_message_at = now
    if user_id:  # an operator answered: the chat is read, the inquiry got its first response
        conv.unread = 0
        if conv.lead_id and (lead := await session.get(Lead, conv.lead_id)):
            leads.mark_contacted(lead)
    await session.flush()
    return await session.get(Message, msg_id)


async def _send(conv: Conversation, msg: Message) -> str:
    if conv.channel is Channel.TELEGRAM:
        bot = get_telegram()
        if bot is None:
            raise SendError("telegram_off")
        sent = await bot.send_message(
            conv.external_id, msg.text, business_connection_id=conv.business_connection_id
        )
        return telegram_msg_id(sent, conv.business_connection_id)
    if conv.channel is Channel.INSTAGRAM:
        ig = get_instagram()
        if ig is None:
            raise SendError("instagram_off")
        return await ig.send_message(conv.external_id, msg.text)
    sms = get_sms_sender()
    if sms is None:
        raise SendError("sms_off")
    return await sms.send(conv.external_id, msg.text, str(msg.id))


async def _finish(session: AsyncSession, msg: Message, values: dict[str, Any]) -> None:
    """Stores the outcome of a send and commits."""
    ext = values.get("external_id")
    msg_id, conv_id = msg.id, msg.conversation_id  # a rollback expires `msg`
    for attempt in range(2):
        try:
            if ext:
                # Instagram may deliver the echo of this very message before we stored its id
                await session.execute(
                    delete(Message).where(
                        Message.conversation_id == conv_id,
                        Message.direction == Direction.OUT,
                        Message.external_id == ext,
                        Message.id != msg_id,
                    )
                )
            await session.execute(update(Message).where(Message.id == msg_id).values(**values))
            await session.commit()
            return
        except IntegrityError:  # the echo was committed between the delete and the update
            await session.rollback()
            if attempt:
                raise


async def deliver(session: AsyncSession, message_id: uuid.UUID) -> MessageStatus | None:
    """Sends one queued message; None = not ours to send (already taken, sent or missing).

    Commits twice: the claim (queued -> sending) before the provider is called, so the per-minute
    job and the immediate task can never both send it, and the outcome afterwards."""
    now = clinic_time.now()
    msg = await session.get(Message, message_id, populate_existing=True)
    if msg is None or msg.status is not MessageStatus.QUEUED:
        return None
    if msg.send_after and msg.send_after > now:
        return msg.status
    if msg.sent_by is None and (allowed := _next_allowed(now)) > now:
        # automatic messages never go out at night, even when they fell due earlier (an outage,
        # a retry after a failure at 19:59)
        await session.execute(
            update(Message)
            .where(Message.id == msg.id, Message.status == MessageStatus.QUEUED)
            .values(send_after=allowed)
        )
        await session.commit()
        return MessageStatus.QUEUED
    claimed = await session.scalar(
        update(Message)
        .where(Message.id == msg.id, Message.status == MessageStatus.QUEUED)
        .values(status=MessageStatus.SENDING, claimed_at=now)
        .returning(Message.id)
    )
    await session.commit()
    if claimed is None:
        return None  # another worker took it
    await session.refresh(msg)
    conv = await session.get(Conversation, msg.conversation_id)
    try:
        ext = await _send(conv, msg)
    except SendError as exc:
        attempts = msg.attempts + 1
        final = attempts >= MAX_ATTEMPTS or str(exc).endswith("_off")
        log.warning("message %s not sent: %s", msg.id, exc)
        values = {
            "attempts": attempts,
            "error": str(exc)[:1000],
            "status": MessageStatus.FAILED if final else MessageStatus.QUEUED,
        }
    except Exception as exc:
        # the provider may have accepted it (e.g. an unreadable answer): never resend blindly
        log.exception("message %s: unexpected error while sending", msg.id)
        values = {
            "attempts": msg.attempts + 1,
            "error": f"unexpected: {type(exc).__name__}",
            "status": MessageStatus.FAILED,
        }
    else:
        values = {
            "status": MessageStatus.SENT, "external_id": ext, "sent_at": clinic_time.now(),
            "error": None,
        }  # fmt: skip
    await _finish(session, msg, values)
    await session.refresh(msg)
    return msg.status


async def recover_interrupted(session: AsyncSession) -> int:
    """Messages a worker took but never finished (crash, restart mid-send).

    Marked failed rather than resent: whether the provider already delivered it is unknown, and
    a duplicate SMS is worse than the operator seeing "not sent" and deciding."""
    timeout = timedelta(minutes=get_settings().messages_sending_timeout_minutes)
    result = await session.execute(
        update(Message)
        .where(
            Message.status == MessageStatus.SENDING,
            Message.claimed_at < clinic_time.now() - timeout,
        )
        .values(status=MessageStatus.FAILED, error="interrupted")
        .returning(Message.id)
    )
    ids = list(result.scalars())
    for message_id in ids:
        log.warning("message %s was interrupted while sending: marked failed", message_id)
    return len(ids)


async def due_messages(session: AsyncSession, limit: int = 100) -> list[uuid.UUID]:
    now = clinic_time.now()
    return list(
        await session.scalars(
            select(Message.id)
            .where(
                Message.status == MessageStatus.QUEUED,
                (Message.send_after.is_(None)) | (Message.send_after <= now),
                Message.attempts < MAX_ATTEMPTS,
            )
            .order_by(Message.created_at)
            .limit(limit)
        )
    )


async def deliver_due(session: AsyncSession) -> int:
    """The per-minute job. Every message is committed on its own: one that breaks doesn't undo
    the ones already sent (which would send them again next minute)."""
    await recover_interrupted(session)
    await session.commit()
    ids = await due_messages(session)
    for message_id in ids:
        try:
            await deliver(session, message_id)
        except Exception:
            log.exception("message %s: delivery crashed", message_id)
            await session.rollback()
    return len(ids)


# --- patient notifications ---------------------------------------------------------------------


async def patient_conversation(session: AsyncSession, patient: Patient) -> Conversation | None:
    """Telegram if the patient ever wrote to the bot, otherwise SMS to the primary number."""
    tg = await session.scalar(
        select(Conversation)
        .where(Conversation.patient_id == patient.id, Conversation.channel == Channel.TELEGRAM)
        .order_by(Conversation.last_message_at.desc().nulls_last())
        .limit(1)
    )
    if tg and get_telegram():
        return tg
    if get_sms_sender() is None:
        return None
    phone = await session.scalar(
        select(PatientPhone.number)
        .where(PatientPhone.patient_id == patient.id)
        .order_by(PatientPhone.is_primary.desc())
        .limit(1)
    )
    if not (number := e164(phone)):
        return None
    conv = await get_conversation(session, Channel.SMS, number, title=patient.full_name)
    conv.patient_id = conv.patient_id or patient.id
    return conv


async def notify_patient(
    session: AsyncSession, patient: Patient, code: str, values: dict[str, Any], dedupe_key: str
) -> Message | None:
    conv = await patient_conversation(session, patient)
    if conv is None:
        return None
    text = await render(session, code, patient.language.value, values)
    if not text:
        return None
    return await queue(session, conv, text, template_code=code, dedupe_key=dedupe_key)


async def _merge_patients(session: AsyncSession, target: uuid.UUID, source: uuid.UUID) -> None:
    await session.execute(
        update(Conversation).where(Conversation.patient_id == source).values(patient_id=target)
    )


patients_service.MERGE_HOOKS.append(_merge_patients)
