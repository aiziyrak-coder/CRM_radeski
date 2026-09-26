from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role, UserSession
from tests.conftest import TEST_PASSWORD, bearer, login, make_user


async def test_login_returns_token_and_sets_refresh_cookie(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)

    resp = await client.post(
        "/api/auth/login", json={"username": "Operator1", "password": TEST_PASSWORD}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "operator1"
    assert body["user"]["role"] == "operator"
    assert "password_hash" not in body["user"]
    cookie = resp.headers["set-cookie"]
    assert "crm_refresh=" in cookie and "HttpOnly" in cookie and "Path=/api/auth" in cookie

    me = await client.get("/api/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["username"] == "operator1"


async def test_wrong_password_is_rejected_and_audited(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)

    resp = await client.post(
        "/api/auth/login", json={"username": "operator1", "password": "nope-nope"}
    )

    assert resp.status_code == 401
    async with SessionLocal() as s:
        actions = list(await s.scalars(select(AuditLog.action)))
    assert actions == ["auth.login_failed"]


async def test_unknown_user_and_inactive_user_get_same_error(client: AsyncClient) -> None:
    await make_user("gone", Role.OPERATOR, active=False)

    for username in ("gone", "never-existed"):
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid_credentials"


async def test_lockout_after_repeated_failures(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    for _ in range(5):
        await client.post("/api/auth/login", json={"username": "operator1", "password": "bad"})

    # even the correct password is refused while locked
    resp = await client.post(
        "/api/auth/login", json={"username": "operator1", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 429


async def test_missing_or_garbage_token_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_refresh_rotates_token(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    await login(client, "operator1")
    first_cookie = client.cookies.get("crm_refresh")

    resp = await client.post("/api/auth/refresh")

    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert client.cookies.get("crm_refresh") != first_cookie


async def test_replayed_refresh_token_after_grace_ends_all_sessions(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    await login(client, "operator1")
    stolen = client.cookies.get("crm_refresh")
    assert (await client.post("/api/auth/refresh")).status_code == 200
    # pretend the rotation happened long ago, beyond the multi-tab grace window
    async with SessionLocal() as s:
        await s.execute(
            update(UserSession)
            .where(UserSession.revoked_at.is_not(None))
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await s.commit()

    client.cookies.set("crm_refresh", stolen, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401

    async with SessionLocal() as s:
        active = list(await s.scalars(select(UserSession).where(UserSession.revoked_at.is_(None))))
    assert active == []


async def test_idle_session_cannot_refresh(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    await login(client, "operator1")
    async with SessionLocal() as s:
        await s.execute(
            update(UserSession).values(last_used_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    resp = await client.post("/api/auth/refresh")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "session_expired"


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    await login(client, "operator1")
    cookie = client.cookies.get("crm_refresh")

    assert (await client.post("/api/auth/logout")).status_code == 204

    client.cookies.set("crm_refresh", cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_change_password(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    token = await login(client, "operator1")

    wrong = await client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong", "new_password": "brand-new-pass"},
        headers=bearer(token),
    )
    assert wrong.status_code == 400

    ok = await client.post(
        "/api/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "brand-new-pass"},
        headers=bearer(token),
    )
    assert ok.status_code == 200
    await login(client, "operator1", "brand-new-pass")


async def test_update_own_language(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    token = await login(client, "operator1")

    resp = await client.patch("/api/auth/me", json={"language": "ru"}, headers=bearer(token))

    assert resp.status_code == 200 and resp.json()["language"] == "ru"


async def test_guessing_one_username_from_many_ips_is_locked(client: AsyncClient) -> None:
    await make_user("operator1", Role.OPERATOR)
    bad = {"username": "operator1", "password": "bad"}
    for n in range(5):  # 4 failures per IP stay under the per-IP limit of 5...
        for _ in range(4):
            await client.post("/api/auth/login", json=bad, headers={"X-Real-IP": f"10.0.0.{n}"})

    # ...but 20 failures for the username lock it from any address
    good = {"username": "operator1", "password": TEST_PASSWORD}
    resp = await client.post("/api/auth/login", json=good, headers={"X-Real-IP": "10.0.0.99"})
    assert resp.status_code == 429
    other = await client.post("/api/auth/login", json={"username": "someone-else", "password": "x"})
    assert other.status_code == 401  # other accounts are not affected
