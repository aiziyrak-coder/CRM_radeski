import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum
from app.modules.users.models import Language


class Script(UUIDPk, Timestamps, Base):
    """Call scripts (TZ 4.6), editable by supervisors. Placeholders in [square brackets]."""

    __tablename__ = "scripts"
    __table_args__ = (UniqueConstraint("code", "language"),)

    code: Mapped[str] = mapped_column(String(30), index=True)
    language: Mapped[Language] = mapped_column(str_enum(Language, 5))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
