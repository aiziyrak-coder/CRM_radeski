import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum


class Role(enum.StrEnum):
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    REGISTRAR = "registrar"
    DOCTOR = "doctor"
    OWNER = "owner"
    ADMIN = "admin"


class Language(enum.StrEnum):
    UZ = "uz"
    RU = "ru"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, 20))
    language: Mapped[Language] = mapped_column(str_enum(Language, 5), default=Language.UZ)
    # FK to branches is added when the catalog module lands (phase 0.6)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # softphone extension (PBX_EXTENSIONS); one per operator
    sip_extension: Mapped[str | None] = mapped_column(String(10), unique=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(UUIDPk, Base):
    """One row per refresh token. Idle + absolute expiry enforce TZ 5 session rules."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
