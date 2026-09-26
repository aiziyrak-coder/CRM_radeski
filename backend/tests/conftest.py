"""Test setup: a dedicated `<db>_test` database and Redis db 15, wiped between tests.

Environment must be configured before `app` is imported, hence the module-level code.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest


def _test_db_url() -> str:
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://crm:crm@localhost:5432/crm")
    parts = urlsplit(base)
    name = parts.path.lstrip("/")
    if not name.endswith("_test"):
        name = f"{name}_test"
    return urlunsplit(parts._replace(path=f"/{name}"))


def _test_redis_url() -> str:
    base = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return urlunsplit(urlsplit(base)._replace(path="/15"))


os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = _test_db_url()
os.environ["REDIS_URL"] = _test_redis_url()

from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.modules  # noqa: E402,F401  - register all models
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.users import service as users_service  # noqa: E402
from app.modules.users.models import Role, User  # noqa: E402
from app.modules.users.schemas import UserCreate  # noqa: E402

TEST_PASSWORD = "test-password-123"


def _asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _prepare_database() -> None:
    target = urlsplit(os.environ["DATABASE_URL"])
    admin_dsn = _asyncpg_dsn(urlunsplit(target._replace(path="/postgres")))
    db_name = target.path.lstrip("/")

    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_prepare_database())


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    redis = Redis.from_url(os.environ["REDIS_URL"])
    await redis.flushdb()
    await redis.aclose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def make_user(username: str, role: Role, *, active: bool = True) -> User:
    async with SessionLocal() as session:
        user = await users_service.create_user(
            session,
            UserCreate(
                username=username, full_name=username.title(), role=role, password=TEST_PASSWORD
            ),
        )
        user.is_active = active
        await session.commit()
        return user


async def login(client: AsyncClient, username: str, password: str = TEST_PASSWORD) -> str:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
