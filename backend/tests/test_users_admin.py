import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user

NEW_USER = {
    "username": "doctor1",
    "full_name": "Doktor Bir",
    "role": "doctor",
    "password": "strong-pass-1",
}


@pytest.fixture
async def admin_token(client: AsyncClient) -> str:
    await make_user("admin", Role.ADMIN)
    return await login(client, "admin")


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.ADMIN])
async def test_non_admins_cannot_manage_users(client: AsyncClient, role: Role) -> None:
    await make_user("someone", role)
    token = await login(client, "someone")

    assert (await client.get("/api/users", headers=bearer(token))).status_code == 403
    resp = await client.post("/api/users", json=NEW_USER, headers=bearer(token))
    assert resp.status_code == 403


async def test_audit_visible_to_admin_and_owner_only(client: AsyncClient) -> None:
    await make_user("owner1", Role.OWNER)
    await make_user("op1", Role.OPERATOR)

    owner = await login(client, "owner1")
    op = await login(client, "op1")

    assert (await client.get("/api/audit", headers=bearer(owner))).status_code == 200
    assert (await client.get("/api/audit", headers=bearer(op))).status_code == 403


async def test_admin_creates_user_and_it_is_audited(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post("/api/users", json=NEW_USER, headers=bearer(admin_token))

    assert resp.status_code == 201
    assert resp.json()["role"] == "doctor"
    await login(client, "doctor1", "strong-pass-1")

    dup = await client.post("/api/users", json=NEW_USER, headers=bearer(admin_token))
    assert dup.status_code == 409

    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(AuditLog.action == "user.create"))
    assert log is not None
    assert log.after["username"] == "doctor1"
    assert "password" not in str(log.after) and "hash" not in str(log.after)


async def test_invalid_username_and_short_password_rejected(
    client: AsyncClient, admin_token: str
) -> None:
    bad_name = {**NEW_USER, "username": "Bad Name!"}
    short_pw = {**NEW_USER, "password": "short"}
    for body in (bad_name, short_pw):
        resp = await client.post("/api/users", json=body, headers=bearer(admin_token))
        assert resp.status_code == 422


async def test_deactivation_blocks_access_immediately(
    client: AsyncClient, admin_token: str
) -> None:
    user = await make_user("op1", Role.OPERATOR)
    op_token = await login(client, "op1")

    resp = await client.patch(
        f"/api/users/{user.id}", json={"is_active": False}, headers=bearer(admin_token)
    )

    assert resp.status_code == 200
    # the still-unexpired access token no longer works
    assert (await client.get("/api/auth/me", headers=bearer(op_token))).status_code == 401


async def test_role_change_is_audited_with_before_and_after(
    client: AsyncClient, admin_token: str
) -> None:
    user = await make_user("op1", Role.OPERATOR)

    await client.patch(
        f"/api/users/{user.id}", json={"role": "supervisor"}, headers=bearer(admin_token)
    )

    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(AuditLog.action == "user.update"))
    assert log.before["role"] == "operator"
    assert log.after["role"] == "supervisor"


async def test_admin_cannot_lock_themselves_out(client: AsyncClient, admin_token: str) -> None:
    me = (await client.get("/api/auth/me", headers=bearer(admin_token))).json()

    for body in ({"is_active": False}, {"role": "operator"}):
        resp = await client.patch(f"/api/users/{me['id']}", json=body, headers=bearer(admin_token))
        assert resp.status_code == 400


async def test_password_reset_ends_user_sessions(client: AsyncClient, admin_token: str) -> None:
    user = await make_user("op1", Role.OPERATOR)
    await login(client, "op1")  # client cookie now belongs to op1's session

    resp = await client.post(
        f"/api/users/{user.id}/password",
        json={"password": "reset-pass-123"},
        headers=bearer(admin_token),
    )

    assert resp.status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401
    await login(client, "op1", "reset-pass-123")
