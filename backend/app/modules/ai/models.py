import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class QaCriterion(UUIDPk, Base):
    """TZ 4.8.1 #3: what every call is scored on; edited by the call-center supervisor."""

    __tablename__ = "qa_criteria"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)  # what the model looks for
    weight: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AnalysisStatus(enum.StrEnum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"  # too short / no speech


class ReviewStatus(enum.StrEnum):
    CONFIRMED = "confirmed"  # the operator accepted the AI's outcome as is
    CORRECTED = "corrected"  # the operator changed it (the difference is kept for evals)


class CallAnalysis(UUIDPk, Timestamps, Base):
    """Transcript + QA analysis of one recorded call (ARXITEKTURA 4.2)."""

    __tablename__ = "call_analyses"

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[AnalysisStatus] = mapped_column(str_enum(AnalysisStatus, 15), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    stt_model: Mapped[str | None] = mapped_column(String(64))
    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    # [{"ch": "operator"|"patient", "start": s, "end": s, "text": str}] in time order
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    language: Mapped[str | None] = mapped_column(String(10))
    conversation_type: Mapped[str | None] = mapped_column(String(30))
    score: Mapped[int | None] = mapped_column(Integer, index=True)
    criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    violations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    red_flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    has_red_flags: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    suggested_outcome: Mapped[str | None] = mapped_column(String(20))
    suggested_reason: Mapped[str | None] = mapped_column(String(50))
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    questions: Mapped[list[str] | None] = mapped_column(JSONB)
    objections: Mapped[list[str] | None] = mapped_column(JSONB)
    # operator's confirmation (plan 4.4)
    review: Mapped[ReviewStatus | None] = mapped_column(str_enum(ReviewStatus, 10))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # supervisor has looked at the red flags (plan 4.5)
    flags_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    flags_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiDigest(UUIDPk, Base):
    """Weekly summary for the supervisor (TZ 4.8.3)."""

    __tablename__ = "ai_digests"

    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    model: Mapped[str | None] = mapped_column(String(64))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # the LLM's write-up
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
