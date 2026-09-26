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
# tests log the same admin in several times within one 30-second TOTP step
os.environ["TOTP_REPLAY_GUARD"] = "false"
os.environ["DATABASE_URL"] = _test_db_url()
os.environ["REDIS_URL"] = _test_redis_url()
# tests never reach the real OpenAI/Telegram/SMS APIs, even with keys in the developer's .env
for _var in ("OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "ESKIZ_EMAIL", "PLAYMOBILE_LOGIN"):
    os.environ[_var] = ""

from datetime import time  # noqa: E402

import pyotp  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import app.modules  # noqa: E402,F401  - register all models
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.text import search_key  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.catalog.models import (  # noqa: E402
    Branch,
    Doctor,
    Resource,
    ResourceKind,
    Service,
    ServiceCategory,
)
from app.modules.patients.models import Patient, PatientKind, PatientPhone  # noqa: E402
from app.modules.scheduling.models import DoctorSchedule  # noqa: E402
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
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
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
    body = resp.json()
    if body.get("totp_required"):  # admins / owner: answer with the authenticator code
        async with SessionLocal() as s:
            user = await s.scalar(select(User).where(User.username == username))
            code = pyotp.TOTP(user.totp_secret).now()
        resp = await client.post(
            "/api/auth/totp", json={"challenge": body["challenge"], "code": code}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
    return body["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- shared domain fixtures -----------------------------------------------------------------


@pytest.fixture
async def clinic() -> dict:
    """Branch, two dermatologists (Mon 09-13), one trichologist, a laser device, services."""
    async with SessionLocal() as s:
        branch = Branch(name_uz="Farg'ona", name_ru="Фергана", is_main=True)
        derm = ServiceCategory(
            site_id="dermatologiya", name_uz="Derm", name_ru="Derm", specialty="dermatologist"
        )
        cosm = ServiceCategory(
            site_id="laser", name_uz="Lazer", name_ru="Лазер", specialty="cosmetologist"
        )
        s.add_all([branch, derm, cosm])
        await s.flush()
        d1 = Doctor(
            name_uz="Doktor A", name_ru="Доктор А", specialties=["dermatologist"], sort_order=1
        )
        d2 = Doctor(
            name_uz="Doktor B",
            name_ru="Доктор Б",
            specialties=["dermatologist", "cosmetologist"],
            sort_order=2,
        )
        tri = Doctor(
            name_uz="Trixolog", name_ru="Трихолог", specialties=["trichologist"], sort_order=3
        )
        consult = Service(
            name_uz="Konsultatsiya",
            name_ru="Консультация",
            category_id=derm.id,
            duration_min=30,
            is_consultation=True,
        )
        laser = Service(
            name_uz="Lazer epilyatsiya",
            name_ru="Лазерная эпиляция",
            category_id=cosm.id,
            duration_min=60,
            device_type="laser_epilation",
            min_interval_days=30,
        )
        s.add_all([d1, d2, tri, consult, laser])
        await s.flush()
        s.add(
            Resource(
                branch_id=branch.id,
                name="Lazer 1",
                kind=ResourceKind.DEVICE,
                device_type="laser_epilation",
            )
        )
        for doc in (d1, d2):
            s.add(
                DoctorSchedule(
                    doctor_id=doc.id,
                    branch_id=branch.id,
                    weekday=0,
                    start_time=time(9),
                    end_time=time(13),
                )
            )
        patient = Patient(
            full_name="Sinov Bemor",
            search_key=search_key("Sinov Bemor"),
            kind=PatientKind.LEGACY,
            tags=[],
            phones=[PatientPhone(number="+998900000001", is_primary=True)],
        )
        s.add(patient)
        await s.commit()
        return {
            "branch": str(branch.id), "d1": str(d1.id), "d2": str(d2.id), "tri": str(tri.id),
            "consult": str(consult.id), "laser": str(laser.id), "patient": str(patient.id),
        }  # fmt: skip


@pytest.fixture
async def op(client: AsyncClient) -> dict:
    await make_user("op1", Role.OPERATOR)
    return bearer(await login(client, "op1"))
