import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class CallDirection(enum.StrEnum):
    IN = "in"
    OUT = "out"


class CallStatus(enum.StrEnum):
    RINGING = "ringing"  # inbound call still in the IVR / queue
    ANSWERED = "answered"
    MISSED = "missed"  # waited in the queue, nobody picked up (or nobody was logged in)
    ABANDONED = "abandoned"  # the caller hung up while waiting
    AFTER_HOURS = "after_hours"
    NO_ANSWER = "no_answer"  # outbound: the patient didn't pick up
    BUSY = "busy"
    FAILED = "failed"  # outbound: trunk down / invalid number


UNANSWERED_INBOUND = (CallStatus.MISSED, CallStatus.ABANDONED, CallStatus.AFTER_HOURS)


class RecordingStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    MISSING = "missing"
    FAILED = "failed"


class Call(UUIDPk, Timestamps, Base):
    """One phone call through the clinic PBX (reported by the Asterisk dialplan)."""

    __tablename__ = "calls"

    pbx_id: Mapped[str] = mapped_column(String(64), unique=True)  # Asterisk UNIQUEID
    direction: Mapped[CallDirection] = mapped_column(str_enum(CallDirection, 5), index=True)
    status: Mapped[CallStatus] = mapped_column(str_enum(CallStatus, 15), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)  # E.164 when valid
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    extension: Mapped[str | None] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wait_seconds: Mapped[int | None] = mapped_column(Integer)
    talk_seconds: Mapped[int | None] = mapped_column(Integer)
    callback_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    recording: Mapped[str | None] = mapped_column(String(100))  # file name in RECORDINGS_DIR
    recording_status: Mapped[RecordingStatus | None] = mapped_column(str_enum(RecordingStatus, 10))
