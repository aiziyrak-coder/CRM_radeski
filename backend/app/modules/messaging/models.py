import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class Channel(enum.StrEnum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    SMS = "sms"


class Direction(enum.StrEnum):
    IN = "in"
    OUT = "out"


class MessageStatus(enum.StrEnum):
    RECEIVED = "received"  # inbound
    QUEUED = "queued"  # outbound, waiting for the worker (or quiet hours to end)
    SENDING = "sending"  # claimed by a worker, the provider is being called
    SENT = "sent"  # the provider accepted it
    DELIVERED = "delivered"  # the provider confirmed delivery (SMS callbacks)
    FAILED = "failed"


class Conversation(UUIDPk, Timestamps, Base):
    """One chat with one person on one channel (TZ 4.4: the shared inbox)."""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("channel", "external_id"),)

    channel: Mapped[Channel] = mapped_column(str_enum(Channel, 10), index=True)
    # Telegram chat id / Instagram-scoped user id / E.164 phone for SMS
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))  # the person's name / @username
    phone: Mapped[str | None] = mapped_column(String(16))  # shared contact (Telegram)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    # Telegram Business: replies must go through the same business connection
    business_connection_id: Mapped[str | None] = mapped_column(String(64))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unread: Mapped[int] = mapped_column(Integer, default=0)


class Message(UUIDPk, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # webhooks are retried by the providers: the same message id is stored once
        Index(
            "uq_messages_external",
            "conversation_id",
            "direction",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[Direction] = mapped_column(str_enum(Direction, 5))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[MessageStatus] = mapped_column(str_enum(MessageStatus, 10), index=True)
    external_id: Mapped[str | None] = mapped_column(String(100), index=True)
    template_code: Mapped[str | None] = mapped_column(String(40))
    ai_draft: Mapped[bool] = mapped_column(default=False)  # the operator started from an AI draft
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # automatic messages (reminders) are sent once: e.g. "reminder:<appointment id>"
    dedupe_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    send_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # when a worker took it for sending: a SENDING row this old was interrupted (worker crash)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageTemplate(UUIDPk, Timestamps, Base):
    """Pre-approved texts (TZ 4.10: reminders are templates, never AI). SMS templates must match
    the text moderated by the provider word for word."""

    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("code", "language"),)

    code: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
