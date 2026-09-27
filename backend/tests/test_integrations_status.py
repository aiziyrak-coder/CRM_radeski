"""Admin integrations page: status of every connection, what is missing, safe provider tests
(fake HTTP transports — nothing reaches the real OpenAI/Telegram/Eskiz/Meta/site) and the
job heartbeats behind "last success"."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.integrations.sms import eskiz
from app.modules.audit.models import AuditLog
from app.modules.integrations_status import heartbeat
from app.modules.integrations_status import service as integrations
from app.modules.telephony.models import Call, CallDirection, CallStatus
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user


@pytest.fixture(autouse=True)
def nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from a blank setup whatever the developer's / container's .env has."""
    s = get_settings()
    for name in (
        "openai_api_key", "pbx_api_secret", "pbx_sip_secret", "sip_host", "telegram_bot_token",
        "telegram_webhook_secret", "instagram_access_token", "instagram_app_secret",
        "instagram_verify_token", "instagram_user_id", "sms_provider", "eskiz_email",
        "eskiz_password", "eskiz_callback_secret", "playmobile_login", "playmobile_password",
        "site_webhook_secret", "site_admin_username", "site_admin_password",
    ):  # fmt: skip
        monkeypatch.setattr(s, name, "")
    monkeypatch.setattr(s, "public_url", "https://crm.devflix.uz")


@pytest.fixture
async def admin(client: AsyncClient) -> dict:
    await make_user("admin", Role.ADMIN)
    return bearer(await login(client, "admin"))


def by_key(items: list[dict]) -> dict[str, dict]:
    return {i["key"]: i for i in items}


async def test_status_shows_what_is_missing_and_never_secrets(
    client: AsyncClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "123:secret-token")
    monkeypatch.setattr(s, "pbx_api_secret", "pbx-secret-value")
    monkeypatch.setattr(s, "pbx_sip_secret", "sip-secret-value")
    monkeypatch.setattr(s, "sms_provider", "playmobile")
    async with SessionLocal() as session:
        session.add(
            Call(pbx_id="u1", direction=CallDirection.IN, status=CallStatus.ANSWERED,
                 phone="+998900000001", started_at=datetime.now(UTC) - timedelta(hours=1))
        )  # fmt: skip
        await session.commit()
    heartbeat.record("site_poll", ok=True, detail={"created": 0})
    heartbeat.record("site_poll", ok=False, error="ConnectError")

    resp = await client.get("/api/system/integrations", headers=admin)
    assert resp.status_code == 200, resp.text
    raw = resp.text
    assert "secret-token" not in raw and "pbx-secret-value" not in raw
    items = by_key(resp.json())
    assert set(items) == {
        "telephony", "trunk", "openai", "telegram", "instagram", "sms", "site_webhook",
        "site_polling", "catalog_sync",
    }  # fmt: skip

    tel = items["telephony"]
    assert tel["configured"] and tel["state"] == "ok" and tel["facts"]["calls_today"] >= 0
    assert items["trunk"]["state"] == "off" and items["trunk"]["missing"] == ["SIP_HOST"]
    assert items["openai"]["missing"] == ["OPENAI_API_KEY"] and items["openai"]["test"] is None
    tg = items["telegram"]
    assert not tg["configured"] and tg["missing"] == ["TELEGRAM_WEBHOOK_SECRET"]
    assert tg["facts"]["webhook_url"].endswith("/api/integrations/telegram/webhook")
    assert items["sms"]["missing"] == ["PLAYMOBILE_LOGIN", "PLAYMOBILE_PASSWORD"]
    assert items["instagram"]["state"] == "off" and len(items["instagram"]["missing"]) == 4
    polling = items["site_polling"]
    assert polling["missing"] == ["SITE_ADMIN_USERNAME", "SITE_ADMIN_PASSWORD"]
    assert polling["facts"]["last_error"] == "ConnectError"  # shown even before it's configured
    # the catalog sync needs nothing but the site address; never ran here
    assert items["catalog_sync"]["configured"] and items["catalog_sync"]["state"] == "warning"


async def test_failing_polling_and_catalog_sync(
    client: AsyncClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "site_admin_username", "crm")
    monkeypatch.setattr(s, "site_admin_password", "pw")
    heartbeat.record("site_poll", ok=False, error="HTTPStatusError")
    heartbeat.record("catalog_sync", ok=True, detail={"services_updated": 3})
    items = by_key((await client.get("/api/system/integrations", headers=admin)).json())
    assert items["site_polling"]["state"] == "error"
    assert items["site_polling"]["facts"]["last_error"] == "HTTPStatusError"
    assert items["site_polling"]["test"] == "site"
    assert items["catalog_sync"]["state"] == "ok"
    assert items["catalog_sync"]["facts"]["last_success_at"]

    heartbeat.record("catalog_sync", ok=False, error="sync_aborted")
    items = by_key((await client.get("/api/system/integrations", headers=admin)).json())
    assert items["catalog_sync"]["state"] == "error"
    assert items["catalog_sync"]["facts"]["last_error"] == "sync_aborted"

    # a manual sync from the settings page afterwards counts as the latest success
    async with SessionLocal() as session:
        session.add(AuditLog(action="catalog.sync", after={}))
        await session.commit()
    items = by_key((await client.get("/api/system/integrations", headers=admin)).json())
    assert items["catalog_sync"]["state"] == "ok"


async def test_integrations_are_admin_only(client: AsyncClient) -> None:
    await make_user("sup", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup"))
    assert (await client.get("/api/system/integrations", headers=sup)).status_code == 403
    assert (await client.post("/api/system/integrations/site/test", headers=sup)).status_code == 403


# --- safe tests against fake providers --------------------------------------------------------


def fake_providers(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.host == "api.openai.com":
            assert request.url.path == "/v1/models" and request.method == "GET"
            data = [{"id": m, "object": "model", "created": 1, "owned_by": "openai"}
                    for m in ("gpt-5.6-luna-2026-05-01", "gpt-4o-transcribe")]  # fmt: skip
            return httpx.Response(200, json={"object": "list", "data": data})
        if request.url.host == "api.telegram.org":
            if url.endswith("/getMe"):
                return httpx.Response(200, json={"ok": True, "result": {"username": "radeski_bot"}})
            if url.endswith("/getWebhookInfo"):
                return httpx.Response(200, json={"ok": True, "result": {
                    "url": "https://crm.devflix.uz/api/integrations/telegram/webhook",
                    "pending_update_count": 2, "last_error_message": "Connection timed out",
                }})  # fmt: skip
        if request.url.host == "notify.eskiz.uz":
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"data": {"token": "tok"}})
            if request.url.path == "/api/user/get-limit":
                assert request.headers["Authorization"] == "Bearer tok"
                return httpx.Response(200, json={"status": "success", "data": {"balance": 12500}})
        if request.url.host == "graph.instagram.com":
            return httpx.Response(200, json={"user_id": "1789", "username": "radeski.clinic"})
        if request.url.host == "api.radeski.uz":
            if request.url.path == "/api/branches":
                return httpx.Response(200, json=[{"id": 1}, {"id": 2}, {"id": 3}])
            if request.url.path == "/api/admin/login":
                return httpx.Response(401, json={"detail": "bad"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_safe_tests_read_only_with_fake_providers(
    client: AsyncClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    for name, value in {
        "openai_api_key": "sk-test", "telegram_bot_token": "123:abc", "sms_provider": "eskiz",
        "eskiz_email": "a@b.uz", "eskiz_password": "pw", "instagram_access_token": "ig",
        "instagram_user_id": "1789", "site_api_url": "https://api.radeski.uz",
        "site_admin_username": "crm", "site_admin_password": "pw",
        "ai_llm_model": "gpt-5.6-luna", "ai_stt_model": "gpt-4o-mini-transcribe",
    }.items():  # fmt: skip
        monkeypatch.setattr(s, name, value)
    monkeypatch.setattr(eskiz, "_token", None)
    calls: list[str] = []
    monkeypatch.setattr(integrations, "_transport", fake_providers(calls))

    async def run(key: str) -> dict:
        resp = await client.post(f"/api/system/integrations/{key}/test", headers=admin)
        assert resp.status_code == 200, resp.text
        return resp.json()

    ai = await run("openai")
    assert ai["ok"] and ai["result"]["models"] == 2
    assert ai["result"]["llm_model_available"]  # a dated snapshot of the configured model
    assert not ai["result"]["stt_model_available"]  # gpt-4o-mini-transcribe isn't listed

    tg = await run("telegram")
    assert tg["result"] == {
        "username": "radeski_bot", "webhook_url": s.public_url + "/api/integrations/telegram/webhook",
        "webhook_ok": True, "pending_updates": 2, "last_error": "Connection timed out",
    }  # fmt: skip
    assert (await run("sms"))["result"] == {"provider": "eskiz", "balance": 12500.0}
    assert (await run("instagram"))["result"] == {"user_id": "1789", "username": "radeski.clinic"}

    site = await run("site")  # public list fine, admin login refused
    assert site == {"ok": False, "error": "auth_failed", "message": None}
    monkeypatch.setattr(s, "site_admin_username", "")
    assert (await run("site"))["result"] == {"branches": 3, "admin": None}

    # nothing but reads went out: no messages, no AI requests that cost money
    assert not any("sendMessage" in c or "/responses" in c or "/sms/send" in c for c in calls)
    async with SessionLocal() as session:
        logs = list(
            await session.scalars(select(AuditLog).where(AuditLog.action == "integration.test"))
        )
    assert len(logs) == 6 and {log.entity_id for log in logs} == {
        "openai", "telegram", "sms", "instagram", "site",
    }  # fmt: skip


async def test_test_errors(
    client: AsyncClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unknown = await client.post("/api/system/integrations/nope/test", headers=admin)
    assert unknown.status_code == 404
    off = (await client.post("/api/system/integrations/telegram/test", headers=admin)).json()
    assert off == {"ok": False, "error": "not_configured", "message": None}
    ai_off = (await client.post("/api/system/integrations/openai/test", headers=admin)).json()
    assert ai_off["error"] == "not_configured"

    s = get_settings()
    monkeypatch.setattr(s, "sms_provider", "playmobile")
    pm = (await client.post("/api/system/integrations/sms/test", headers=admin)).json()
    assert pm["error"] == "not_supported"

    monkeypatch.setattr(s, "telegram_bot_token", "123:abc")

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    monkeypatch.setattr(integrations, "_transport", httpx.MockTransport(refuse))
    bad = (await client.post("/api/system/integrations/telegram/test", headers=admin)).json()
    assert bad == {"ok": False, "error": "provider_error", "message": "telegram: Unauthorized"}
    assert "123:abc" not in json.dumps(bad)


def test_heartbeat_failing_flag() -> None:
    heartbeat.record("catalog_sync", ok=True, detail={"x": 1})
    import asyncio

    hb = asyncio.run(heartbeat.read("catalog_sync"))
    assert hb["last_ok"] and hb["detail"] == {"x": 1} and not hb["failing"]
    heartbeat.record("catalog_sync", ok=False, error="boom")
    hb = asyncio.run(heartbeat.read("catalog_sync"))
    assert hb["failing"] and hb["error"] == "boom"


def test_catalog_job_records_its_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.modules.catalog import sync
    from app.workers import jobs

    async def aborted(session):
        raise sync.SyncAbortedError("doctors", 0, 11)

    monkeypatch.setattr(sync, "sync_from_site", aborted)
    assert jobs.sync_catalog() == {"aborted": 1}
    hb = asyncio.run(heartbeat.read("catalog_sync"))
    assert hb["failing"] and hb["error"] == "sync_aborted"
