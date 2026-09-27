"""0.2b: admins and the owner log in with an authenticator code."""

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import cli
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role, User
from tests.conftest import TEST_PASSWORD, bearer, login, make_user


async def secret_of(username: str) -> str:
    async with SessionLocal() as s:
        return (await s.scalar(select(User).where(User.username == username))).totp_secret


async def password_step(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_admin_enrols_then_needs_the_code(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "totp_replay_guard", True)
    await make_user("boss", Role.ADMIN)

    first = await password_step(client, "boss")
    assert "access_token" not in first and first["setup"] is True
    assert first["otpauth_uri"].startswith("otpauth://totp/Radeski%20CRM:boss")
    assert first["qr"].startswith("data:image/svg+xml;base64,")
    # the challenge is not an access token
    assert (await client.get("/api/auth/me", headers=bearer(first["challenge"]))).status_code == 401

    wrong = await client.post(
        "/api/auth/totp", json={"challenge": first["challenge"], "code": "000000"}
    )
    assert wrong.status_code == 401 and wrong.json()["detail"] == "invalid_code"
    code = pyotp.TOTP(first["secret"]).now()
    ok = await client.post("/api/auth/totp", json={"challenge": first["challenge"], "code": code})
    assert ok.status_code == 200 and ok.json()["user"]["totp_enabled"] is True

    # enrolled: no QR any more, and the same code can't be used twice
    second = await password_step(client, "boss")
    assert second["setup"] is False and second["secret"] is None
    replay = await client.post(
        "/api/auth/totp", json={"challenge": second["challenge"], "code": code}
    )
    assert replay.status_code == 401

    garbage = await client.post("/api/auth/totp", json={"challenge": "x" * 20, "code": "123456"})
    assert garbage.status_code == 401 and garbage.json()["detail"] == "challenge_expired"


async def test_operators_log_in_with_password_only(client: AsyncClient) -> None:
    await make_user("op1", Role.OPERATOR)
    body = await password_step(client, "op1")
    assert body["access_token"] and body["user"]["totp_enabled"] is False


async def test_admin_can_reset_a_lost_authenticator(client: AsyncClient) -> None:
    await make_user("boss", Role.ADMIN)
    await make_user("owner1", Role.OWNER)
    admin = bearer(await login(client, "boss"))
    await login(client, "owner1")  # enrols
    owner_id = (await client.get("/api/users", headers=admin)).json()
    [owner] = [u for u in owner_id if u["username"] == "owner1"]
    assert owner["totp_enabled"] is True

    resp = await client.post(f"/api/users/{owner['id']}/totp-reset", headers=admin)
    assert resp.status_code == 204
    again = await password_step(client, "owner1")
    assert again["setup"] is True and again["secret"] == await secret_of("owner1")


async def test_code_guessing_is_limited_across_password_logins(client: AsyncClient) -> None:
    """Knowing the password must not buy unlimited code guesses: the code counter is per user,
    survives a correct password and locks the second step (TZ 5, 2FA)."""
    await make_user("boss", Role.ADMIN)
    await login(client, "boss")  # enrolled
    secret = await secret_of("boss")
    good = pyotp.TOTP(secret).now()
    wrong = "000000" if good != "000000" else "111111"

    async def guess(challenge: str, code: str = wrong) -> int:
        resp = await client.post("/api/auth/totp", json={"challenge": challenge, "code": code})
        return resp.status_code

    first = (await password_step(client, "boss"))["challenge"]
    assert [await guess(first) for _ in range(3)] == [401, 401, 401]
    # a challenge is good for a limited number of codes, then a new password step is needed
    exhausted = await client.post("/api/auth/totp", json={"challenge": first, "code": good})
    assert exhausted.status_code == 401 and exhausted.json()["detail"] == "challenge_expired"

    # the correct password again does not reset the code counter
    second = (await password_step(client, "boss"))["challenge"]
    assert [await guess(second) for _ in range(2)] == [401, 401]  # 5 wrong codes in total

    third = (await password_step(client, "boss"))["challenge"]
    locked = await client.post("/api/auth/totp", json={"challenge": third, "code": good})
    assert locked.status_code == 429 and locked.json()["detail"] == "too_many_attempts"

    async with SessionLocal() as s:
        actions = list(await s.scalars(select(AuditLog.action)))
    assert actions.count("auth.totp_failed") == 5 and "auth.totp_locked" in actions


async def test_successful_code_resets_counter_and_burns_the_challenge(
    client: AsyncClient,
) -> None:
    await make_user("boss", Role.ADMIN)
    await login(client, "boss")
    secret = await secret_of("boss")

    for _ in range(2):  # 4 wrong codes, then a correct one: the counter starts over
        challenge = (await password_step(client, "boss"))["challenge"]
        for _ in range(2):
            await client.post("/api/auth/totp", json={"challenge": challenge, "code": "000000"})
    challenge = (await password_step(client, "boss"))["challenge"]
    ok = await client.post(
        "/api/auth/totp", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()}
    )
    assert ok.status_code == 200
    # the same challenge can't open a second session
    again = await client.post(
        "/api/auth/totp", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()}
    )
    assert again.status_code == 401 and again.json()["detail"] == "challenge_expired"

    challenge = (await password_step(client, "boss"))["challenge"]
    for _ in range(3):
        resp = await client.post("/api/auth/totp", json={"challenge": challenge, "code": "000000"})
        assert resp.status_code == 401  # not locked: only 3 failures since the success


async def test_totp_role_promotion_ends_existing_sessions(client: AsyncClient) -> None:
    await make_user("admin", Role.ADMIN)
    admin = bearer(await login(client, "admin"))
    op = await make_user("op1", Role.OPERATOR)
    op_token = await login(client, "op1")  # password only; the client holds op1's cookie

    resp = await client.patch(f"/api/users/{op.id}", json={"role": "owner"}, headers=admin)
    assert resp.status_code == 200
    # neither the refresh cookie nor the access token issued for the old role work any more
    assert (await client.post("/api/auth/refresh")).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer(op_token))).status_code == 401
    body = await password_step(client, "op1")
    assert body["totp_required"] is True and "access_token" not in body


async def test_cli_reset_totp_is_audited_and_ends_sessions(client: AsyncClient) -> None:
    await make_user("owner1", Role.OWNER)
    await login(client, "owner1")

    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.username == "owner1"))
        await cli.reset_totp(s, user)
        await s.commit()

    assert (await client.post("/api/auth/refresh")).status_code == 401
    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(AuditLog.action == "user.totp_reset"))
        user = await s.scalar(select(User).where(User.username == "owner1"))
    assert log is not None and log.after == {"via": "cli"} and user.totp_enabled is False


async def test_2fa_can_be_switched_off_for_every_role(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOTP_ROLES= (empty) in .env: the clinic chose password-only logins."""
    monkeypatch.setattr(get_settings(), "totp_roles", "")
    await make_user("boss", Role.ADMIN)
    resp = await password_step(client, "boss")
    assert "access_token" in resp and "challenge" not in resp
