"""Audit log page: filters (user, action group, entity, clinic-day range), facets, paging."""

from datetime import timedelta

from httpx import AsyncClient

from app.core import clinic_time
from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user


async def _seed() -> dict:
    admin = await make_user("admin", Role.ADMIN)
    sup = await make_user("sup", Role.SUPERVISOR)
    today = clinic_time.today()
    start, _ = clinic_time.day_bounds(today)
    old, _ = clinic_time.day_bounds(today - timedelta(days=10))
    async with SessionLocal() as s:
        s.add_all(
            [
                AuditLog(action="patient.update", user_id=sup.id, entity="patient",
                         entity_id="p1", before={"full_name": "A"}, after={"full_name": "B"},
                         created_at=start + timedelta(hours=2)),
                AuditLog(action="patient.view", user_id=sup.id, entity="patient",
                         entity_id="p1", created_at=start + timedelta(hours=3)),
                AuditLog(action="campaign.create", user_id=admin.id, entity="campaign",
                         entity_id="c1", after={"name": "X"}, created_at=old),
                AuditLog(action="auth.login_failed", created_at=old + timedelta(hours=1)),
            ]
        )  # fmt: skip
        await s.commit()
    return {"admin": admin, "sup": sup, "today": today}


async def test_audit_filters_and_facets(client: AsyncClient) -> None:
    seed = await _seed()
    h = bearer(await login(client, "admin"))

    async def ids(query: str) -> list[str]:
        resp = await client.get(f"/api/audit?{query}", headers=h)
        assert resp.status_code == 200, resp.text
        # the admin's own login (and 2FA enrolment) happen "today" too
        skip = {"auth.login", "auth.totp_enrolled"}
        return [i["action"] for i in resp.json()["items"] if i["action"] not in skip]

    assert await ids("group=patient") == ["patient.view", "patient.update"]
    assert await ids("action=patient.update") == ["patient.update"]
    assert await ids(f"user_id={seed['sup'].id}") == ["patient.view", "patient.update"]
    assert await ids("entity=campaign&entity_id=c1") == ["campaign.create"]
    today = seed["today"].isoformat()
    assert set(await ids(f"date_from={today}&date_to={today}")) == {
        "patient.view", "patient.update",
    }  # fmt: skip
    older = (seed["today"] - timedelta(days=1)).isoformat()
    assert await ids(f"date_to={older}") == ["auth.login_failed", "campaign.create"]
    bad = await client.get(f"/api/audit?date_from={today}&date_to={older}", headers=h)
    assert bad.status_code == 422 and bad.json()["detail"] == "bad_range"

    page = (await client.get("/api/audit?group=patient&limit=1&offset=1", headers=h)).json()
    assert page["total"] == 2 and [i["action"] for i in page["items"]] == ["patient.update"]
    assert page["items"][0]["before"] == {"full_name": "A"}
    assert page["items"][0]["user_name"] == "Sup"

    facets = (await client.get("/api/audit/facets", headers=h)).json()
    actions = {a["action"]: a["count"] for a in facets["actions"]}
    assert actions["patient.update"] == 1 and "auth.login" in actions
    assert facets["entities"] == ["campaign", "patient"]
    assert {u["name"] for u in facets["users"]} >= {"Admin", "Sup"}


async def test_audit_is_admin_and_owner_only(client: AsyncClient) -> None:
    await make_user("sup", Role.SUPERVISOR)
    h = bearer(await login(client, "sup"))
    assert (await client.get("/api/audit", headers=h)).status_code == 403
    assert (await client.get("/api/audit/facets", headers=h)).status_code == 403
