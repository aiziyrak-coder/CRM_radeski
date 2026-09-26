from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    resp = await client.get("/api/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"db": "ok", "redis": "ok"}


async def test_system_status_for_staff_only(client: AsyncClient) -> None:
    from app.modules.users.models import Role
    from tests.conftest import bearer, login, make_user

    await make_user("op1", Role.OPERATOR)
    await make_user("sup1", Role.SUPERVISOR)
    await make_user("doc1", Role.DOCTOR)
    assert (await client.get("/api/system/status")).status_code == 401
    doc = bearer(await login(client, "doc1"))
    assert (await client.get("/api/system/status", headers=doc)).status_code == 403
    op = (await client.get("/api/system/status", headers=bearer(await login(client, "op1")))).json()
    assert op["today"] == {
        "missed_calls": 0, "unread_chats": 0, "missed_open": 0, "leads_sla_breached": 0,
    }  # fmt: skip
    assert "integrations" not in op
    sup = (
        await client.get("/api/system/status", headers=bearer(await login(client, "sup1")))
    ).json()
    assert sup["integrations"]["ai"] is False and sup["qa"]["red_flags_open"] == 0
    assert sup["attention"]["messages_queued"] == 0
