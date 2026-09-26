import enum
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_settings = get_settings()


class Base(DeclarativeBase):
    # fetch server-generated values (created_at, updated_at) via RETURNING on INSERT *and* UPDATE,
    # so reading them after a flush never triggers lazy IO (not allowed with asyncio)
    __mapper_args__ = {"eager_defaults": True}


def str_enum(enum_cls: type[enum.StrEnum], length: int = 32) -> Enum:
    """Stores enum *values* ("operator") as VARCHAR — readable in SQL, no PG enum migrations."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
    )


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    # tests run each case in its own event loop; pooled asyncpg connections can't cross loops
    poolclass=NullPool if _settings.environment == "test" else None,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
