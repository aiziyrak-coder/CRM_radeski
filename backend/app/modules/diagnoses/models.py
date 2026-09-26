import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class MappingStatus(enum.StrEnum):
    PENDING = "pending"  # no rule matched; needs a human (or AI) suggestion
    SUGGESTED = "suggested"  # a rule/AI proposed a category; not applied until approved
    APPROVED = "approved"  # a doctor/admin confirmed; applied to patient_conditions


class MappingMethod(enum.StrEnum):
    RULE = "rule"
    AI = "ai"
    MANUAL = "manual"


class DiagnosisMapping(UUIDPk, Timestamps, Base):
    """One row per distinct (normalized) diagnosis text found in patient_conditions."""

    __tablename__ = "diagnosis_mappings"

    text: Mapped[str] = mapped_column(String(500), unique=True)
    category_code: Mapped[str | None] = mapped_column(String(50), index=True)
    method: Mapped[MappingMethod | None] = mapped_column(str_enum(MappingMethod, 10))
    status: Mapped[MappingStatus] = mapped_column(str_enum(MappingStatus, 10), index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
