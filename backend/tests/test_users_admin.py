import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Branch
from app.modules.users import service as users_service
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserUpdate
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


async def test_explicit_nulls_leave_required_fields_alone(
    client: AsyncClient, admin_token: str
) -> None:
    user = await make_user("op1", Role.OPERATOR)
    resp = await client.patch(
        f"/api/users/{user.id}",
        json={"full_name": None, "role": None, "language": None, "is_active": None},
        headers=bearer(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Op1" and body["role"] == "operator" and body["is_active"]


async def test_branch_must_exist(client: AsyncClient, admin_token: str) -> None:
    missing = str(uuid.uuid4())
    resp = await client.post(
        "/api/users", json={**NEW_USER, "branch_id": missing}, headers=bearer(admin_token)
    )
    assert resp.status_code == 400 and resp.json()["detail"] == "branch_not_found"

    user = await make_user("op1", Role.OPERATOR)
    resp = await client.patch(
        f"/api/users/{user.id}", json={"branch_id": missing}, headers=bearer(admin_token)
    )
    assert resp.status_code == 400 and resp.json()["detail"] == "branch_not_found"

    async with SessionLocal() as s:
        branch = Branch(name_uz="Qo'qon", name_ru="Коканд")
        s.add(branch)
        await s.commit()
    resp = await client.patch(
        f"/api/users/{user.id}", json={"branch_id": str(branch.id)}, headers=bearer(admin_token)
    )
    assert resp.status_code == 200 and resp.json()["branch_id"] == str(branch.id)


async def test_role_change_ends_sessions(client: AsyncClient, admin_token: str) -> None:
    user = await make_user("op1", Role.OPERATOR)
    op_token = await login(client, "op1")

    resp = await client.patch(
        f"/api/users/{user.id}", json={"role": "registrar"}, headers=bearer(admin_token)
    )

    assert resp.status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer(op_token))).status_code == 401
    # a plain update (no role change) keeps the user's sessions
    fresh = await login(client, "op1")
    await client.patch(
        f"/api/users/{user.id}", json={"language": "ru"}, headers=bearer(admin_token)
    )
    assert (await client.get("/api/auth/me", headers=bearer(fresh))).status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 200


async def test_extension_taken(client: AsyncClient, admin_token: str) -> None:
    a = await make_user("op1", Role.OPERATOR)
    b = await make_user("op2", Role.OPERATOR)
    ok = await client.patch(
        f"/api/users/{a.id}", json={"sip_extension": "101"}, headers=bearer(admin_token)
    )
    assert ok.status_code == 200
    taken = await client.patch(
        f"/api/users/{b.id}", json={"sip_extension": "101"}, headers=bearer(admin_token)
    )
    assert taken.status_code == 409 and taken.json()["detail"] == "extension_taken"
    # the database constraint backs the check when two admins race (409, not a 500)
    async with SessionLocal() as s:
        user_b = await s.get(User, b.id)
        with pytest.raises(users_service.ExtensionTakenError):
            await users_service.update_user(s, user_b, UserUpdate(sip_extension="101"))
