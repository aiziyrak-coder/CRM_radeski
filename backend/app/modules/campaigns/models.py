import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class CampaignStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"


class Campaign(UUIDPk, Timestamps, Base):
    """TZ 4.9: call a segment of the base with a daily limit (one operator has ~30-50 slots/day)."""

    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(255))
    # {"kinds": [...], "categories": [...], "districts": [...], "sources": [...],
    #  "last_visit_before_days": 180, "gender": "female", "age_min": 18, "age_max": 60}
    segment: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    script_code: Mapped[str | None] = mapped_column(String(30))
    daily_limit: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[CampaignStatus] = mapped_column(
        str_enum(CampaignStatus, 10), default=CampaignStatus.DRAFT, index=True
    )
    ends_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
