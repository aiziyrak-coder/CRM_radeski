"""0.2b: admins and the owner log in with an authenticator code."""

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
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
