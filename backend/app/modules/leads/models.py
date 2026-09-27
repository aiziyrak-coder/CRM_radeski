import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum
from app.modules.patients.models import Source


class LeadChannel(enum.StrEnum):
    CALL = "call"
    MISSED_CALL = "missed_call"
    WEBSITE = "website"
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    WALK_IN = "walk_in"
    MANUAL = "manual"


class LeadStage(enum.StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    BOOKED = "booked"
    CONFIRMED = "confirmed"  # the booked visit was confirmed (by phone or at the desk)
    VISITED = "visited"
    LATER = "later"
    LOST = "lost"


OPEN_STAGES = (LeadStage.NEW, LeadStage.CONTACTED, LeadStage.LATER)
# TZ 4.4 funnel: new -> contacted -> booked -> confirmed -> visited (lost / later are side exits)
FUNNEL = (
    LeadStage.NEW, LeadStage.CONTACTED, LeadStage.BOOKED, LeadStage.CONFIRMED, LeadStage.VISITED,
)  # fmt: skip


class Lead(UUIDPk, Timestamps, Base):
    """An inquiry (TZ 4.4): every call, form or message that may become a visit."""

    __tablename__ = "leads"

    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"), index=True)
    phone: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[LeadChannel] = mapped_column(str_enum(LeadChannel, 15), index=True)
    source: Mapped[Source | None] = mapped_column(str_enum(Source, 20))
    interest: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[LeadStage] = mapped_column(
        str_enum(LeadStage, 10), default=LeadStage.NEW, index=True
    )
    lost_reason: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    # id in the originating system (site form id, Telegram chat id ...), for idempotent intake
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeadStageChange(UUIDPk, Base):
    """Stage history of an inquiry (who moved it, when and why) for the lead drawer."""

    __tablename__ = "lead_stage_changes"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    old_stage: Mapped[LeadStage | None] = mapped_column(str_enum(LeadStage, 10))
    new_stage: Mapped[LeadStage] = mapped_column(str_enum(LeadStage, 10))
    reason: Mapped[str | None] = mapped_column(String(50))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
