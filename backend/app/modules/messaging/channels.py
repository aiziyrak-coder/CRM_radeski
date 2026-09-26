"""Incoming webhooks: Telegram updates and Instagram messaging events -> inbox."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.modules.messaging import service
from app.modules.messaging.models import Channel, Direction, MessageStatus

# text shown for non-text messages (media isn't downloaded in v1)
PLACEHOLDERS = {
    "photo": "[rasm]",
    "voice": "[ovozli xabar]",
    "audio": "[audio]",
    "video": "[video]",
    "video_note": "[video xabar]",
    "document": "[fayl]",
    "sticker": "[stiker]",
    "location": "[joylashuv]",
}
CONTACT_THANKS = {
    "uz": "Rahmat! Operatorimiz tez orada siz bilan bog'lanadi.",
    "ru": "Спасибо! Оператор скоро свяжется с вами.",
}


def _text(msg: dict[str, Any]) -> str:
    if msg.get("text") or msg.get("caption"):
        return msg.get("text") or msg.get("caption")
    if contact := msg.get("contact"):
        return f"[kontakt: {contact.get('phone_number', '')}]"
    return next((label for key, label in PLACEHOLDERS.items() if key in msg), "[xabar]")


def _reply(chat_id: int, text: str, markup: dict[str, Any] | None = None) -> dict[str, Any]:
    """Telegram runs a method returned as the webhook response: no extra API call needed."""
    body: dict[str, Any] = {"method": "sendMessage", "chat_id": chat_id, "text": text}
    if markup:
        body["reply_markup"] = markup
    return body


async def _log_outbound(
    session: AsyncSession,
    channel: Channel,
    chat_id: str,
    text: str,
    title: str | None = None,
    external_id: str | None = None,
) -> None:
    """A message that reached the person without our queue (bot reply, the clinic's own app)."""
    conv = await service.get_conversation(session, channel, chat_id, title=title)
    await service.store_message(
        session, conv, Direction.OUT, text, MessageStatus.SENT, external_id, clinic_time.now()
    )
    await session.flush()


def _bot_id() -> int | None:
    """The bot's own user id is the first part of its token ("123456:ABC...")."""
    head = get_settings().telegram_bot_token.split(":", 1)[0]
    return int(head) if head.isdigit() else None


async def telegram_update(session: AsyncSession, update: dict[str, Any]) -> dict[str, Any] | None:
    msg = update.get("message") or update.get("business_message")
    if not msg or (msg.get("chat") or {}).get("type") != "private":
        return None  # groups, channels, edits, connection events
    chat, sender = msg["chat"], msg.get("from") or {}
    chat_id = str(chat["id"])
    business = msg.get("business_connection_id")
    name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
    title = name or (f"@{chat['username']}" if chat.get("username") else None)
    lang = "ru" if (sender.get("language_code") or "").startswith("ru") else "uz"
    text = _text(msg)

    if business and sender.get("id") != chat["id"]:
        # an outgoing message of the Business account. Sent by this bot = an operator's reply
        # from the CRM, already in the history; otherwise the clinic answered from its own
        # Telegram app: keep the history whole
        bot_id = _bot_id()
        if bot_id is not None and (msg.get("sender_business_bot") or {}).get("id") == bot_id:
            return None
        await _log_outbound(
            session, Channel.TELEGRAM, chat_id, text, title,
            external_id=service.telegram_msg_id(msg.get("message_id"), business),
        )  # fmt: skip
        return None
    if text.strip() == "/start" and not business:
        welcome = await service.render(session, "telegram_welcome", lang, {})
        if not welcome:
            return None
        await _log_outbound(session, Channel.TELEGRAM, chat_id, welcome, title)
        label = "📞 Telefon raqamni yuborish" if lang == "uz" else "📞 Отправить номер"
        keyboard = {
            "keyboard": [[{"text": label, "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
        return _reply(chat["id"], welcome, keyboard)

    contact = msg.get("contact") or {}
    # only the "send my number" button proves the number is the sender's own: it sets user_id.
    # A forwarded card or a typed contact of someone else must not link the chat to a patient
    sender_id = sender.get("id")
    own_contact = bool(contact) and sender_id is not None and contact.get("user_id") == sender_id
    received = await service.receive(
        session, Channel.TELEGRAM, chat_id, text, title=title,
        external_msg_id=service.telegram_msg_id(msg.get("message_id"), business),
        phone=contact.get("phone_number") if own_contact else None,
        business_connection_id=business,
    )  # fmt: skip
    if received is None:  # Telegram re-delivered an update we already handled
        return None
    if own_contact and not business:
        await _log_outbound(session, Channel.TELEGRAM, chat_id, CONTACT_THANKS[lang], title)
        return _reply(chat["id"], CONTACT_THANKS[lang], {"remove_keyboard": True})
    return None


async def instagram_event(session: AsyncSession, payload: dict[str, Any], own_id: str) -> int:
    handled = 0
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender = str((event.get("sender") or {}).get("id", ""))
            recipient = str((event.get("recipient") or {}).get("id", ""))
            if not message or not sender:
                continue
            text = message.get("text") or ("[rasm]" if message.get("attachments") else "[xabar]")
            if message.get("is_echo") or sender == own_id:
                if not recipient:
                    continue
                # our own message: sent from the CRM (its mid is stored already -> skipped) or
                # from the Instagram app by the clinic (kept, so the history is whole)
                await _log_outbound(
                    session, Channel.INSTAGRAM, recipient, text, external_id=message.get("mid")
                )
            else:
                await service.receive(
                    session, Channel.INSTAGRAM, sender, text, title="Instagram",
                    external_msg_id=message.get("mid"),
                )  # fmt: skip
            handled += 1
    await session.flush()
    return handled
