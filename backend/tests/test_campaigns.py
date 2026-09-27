"""Campaigns (TZ 4.9, 4.8.3): segment filters and make-up, suggested segments, editing,
results (calls, dial rate, bookings, visits, refusal reasons), members and the AI summary."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.text import search_key
from app.integrations.llm import LlmError
from app.modules.audit.models import AuditLog
from app.modules.campaigns.summary import CampaignSummaryOut
from app.modules.patients.models import (
    Patient,
    PatientCondition,
    PatientKind,
    PatientPhone,
    Source,
)
from app.modules.scheduling.models import Appointment, AppointmentStatus
from app.modules.tasks.models import Task, TaskAttempt, TaskType
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user


@pytest.fixture
async def sup(client: AsyncClient) -> dict:
    await make_user("sup1", Role.SUPERVISOR)
    return bearer(await login(client, "sup1"))


_n = 0


async def patient(
    name: str,
    kind: PatientKind = PatientKind.LEGACY,
    *,
    district: str | None = "Oltiariq",
    tags: list[str] | None = None,
    source: Source | None = None,
    category: str | None = None,
    last_visit_days: int | None = None,
) -> uuid.UUID:
    global _n
    _n += 1
    async with SessionLocal() as s:
        p = Patient(
            full_name=name, search_key=search_key(name), kind=kind, tags=tags or [],
            district=district, source=source,
            last_visit_at=datetime.now(UTC) - timedelta(days=last_visit_days)
            if last_visit_days is not None else None,
            phones=[PatientPhone(number=f"+99890{_n:07d}", is_primary=True)],
        )  # fmt: skip
        if category:
            p.conditions = [
                PatientCondition(raw_text=category, category_code=category, source="test")
            ]
        s.add(p)
        await s.commit()
        return p.id


# --- segment ----------------------------------------------------------------------------------


async def test_tags_filter_and_audience_breakdown(client: AsyncClient, sup: dict) -> None:
    await patient("Aziza", tags=["vip"], category="vitiligo", source=Source.INSTAGRAM)
    await patient("Bobur", tags=["vip", "laser"], district="Qo'qon", category="acne")
    await patient("Dilnoza", tags=["laser"], category="acne", last_visit_days=30)
    await patient("Eski", kind=PatientKind.COLD, district=None)

    vip = await client.post("/api/campaigns/preview", json={"tags": ["vip"]}, headers=sup)
    assert vip.json() == {"audience": 2}
    either = await client.post(
        "/api/campaigns/preview", json={"tags": ["vip", "laser"]}, headers=sup
    )
    assert either.json() == {"audience": 3}  # any of the tags

    resp = await client.post("/api/campaigns/audience", json={}, headers=sup)
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["audience"] == 4
    assert {r["key"]: r["count"] for r in b["by_kind"]} == {"legacy": 3, "cold": 1}
    assert {r["key"]: r["count"] for r in b["by_district"]} == {
        "Oltiariq": 2, "Qo'qon": 1, None: 1,
    }  # fmt: skip
    assert {r["key"]: r["count"] for r in b["by_category"]} == {"acne": 2, "vitiligo": 1}
    assert {r["key"]: r["count"] for r in b["by_source"]} == {"instagram": 1, None: 3}
    assert {r["key"]: r["count"] for r in b["by_recency"]} == {"never": 3, "recent": 1}

    tags = (await client.get("/api/campaigns/tags", headers=sup)).json()
    assert tags == [{"tag": "laser", "count": 2}, {"tag": "vip", "count": 2}]


async def test_campaign_endpoints_are_for_managers(client: AsyncClient) -> None:
    await make_user("op9", Role.OPERATOR)
    op = bearer(await login(client, "op9"))
    for method, url in (
        ("get", "/api/campaigns/suggestions"),
        ("post", "/api/campaigns/audience"),
        ("get", f"/api/campaigns/{uuid.uuid4()}"),
        ("get", f"/api/campaigns/{uuid.uuid4()}/members"),
        ("post", f"/api/campaigns/{uuid.uuid4()}/ai-summary"),
    ):
        kwargs: dict[str, Any] = {"json": {}} if method == "post" else {}
        resp = await getattr(client, method)(url, headers=op, **kwargs)
        assert resp.status_code == 403, url


# --- suggestions (TZ 4.9 capacity) ------------------------------------------------------------


async def test_suggestions_put_targeted_old_patients_first_and_cold_base_last(
    client: AsyncClient, sup: dict
) -> None:
    for i in range(3):
        await patient(f"Vit {i}", category="vitiligo", last_visit_days=400)
    for i in range(2):
        await patient(f"Soch {i}", category="alopecia_androgenic", last_visit_days=300)
    await patient("Yaqinda", category="alopecia_androgenic", last_visit_days=10)
    await patient("Faol", kind=PatientKind.ACTIVE, last_visit_days=200)
    await patient("Sovuq", kind=PatientKind.COLD)

    items = (await client.get("/api/campaigns/suggestions", headers=sup)).json()
    by = {i["code"]: i for i in items}
    assert items[0]["code"] == "excimer" and by["excimer"]["audience"] == 3
    # only patients not seen for reactivation_after_days are in a category segment
    alopecia = by["category:alopecia_androgenic"]
    assert alopecia["audience"] == 2 and alopecia["specialty"] == "trichologist"
    assert "category:vitiligo" not in by  # already covered by the Excimer suggestion
    assert by["reactivation"]["audience"] == 1
    assert items[-1]["code"] == "cold" and items[-1]["audience"] == 1
    assert "leads" not in by  # empty segments are not suggested

    # one click prefills a campaign; the suggestion then names it
    body = {"name": "Excimer", "segment": by["excimer"]["segment"]}
    assert (await client.post("/api/campaigns", json=body, headers=sup)).status_code == 201
    again = {
        i["code"]: i for i in (await client.get("/api/campaigns/suggestions", headers=sup)).json()
    }
    assert again["excimer"]["campaign"] == "Excimer"
    assert again["cold"]["campaign"] is None


# --- editing ----------------------------------------------------------------------------------


async def test_edit_campaign_is_audited_and_finished_ones_are_frozen(
    client: AsyncClient, sup: dict
) -> None:
    await patient("Aziza", tags=["vip"])
    body = {"name": "VIP", "segment": {"tags": ["vip"]}, "daily_limit": 10}
    created = (await client.post("/api/campaigns", json=body, headers=sup)).json()
    assert created["description"] is None and created["progress"]["remaining"] == 1

    edit = {
        **body, "description": "Yangi lazer haqida xabar", "daily_limit": 25,
        "script_code_b": "laser", "ends_on": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }  # fmt: skip
    resp = await client.put(f"/api/campaigns/{created['id']}", json=edit, headers=sup)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["description"] == "Yangi lazer haqida xabar" and out["daily_limit"] == 25
    assert out["script_code_b"] == "laser" and out["ends_on"]
    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(AuditLog.action == "campaign.update"))
    assert log.before == {
        "description": None, "daily_limit": 10, "script_code_b": None, "ends_on": None,
    }  # fmt: skip
    assert log.after["daily_limit"] == 25 and "name" not in log.after

    same = await client.put(
        f"/api/campaigns/{created['id']}", json={**edit, "script_code_b": "reactivation"},
        headers=sup,
    )  # fmt: skip
    assert same.status_code == 400 and same.json()["detail"] == "same_script"

    url = f"/api/campaigns/{created['id']}"
    await client.post(f"{url}/status", json={"status": "finished"}, headers=sup)
    frozen = await client.put(url, json=edit, headers=sup)
    assert frozen.status_code == 400 and frozen.json()["detail"] == "campaign_finished"


# --- results ----------------------------------------------------------------------------------


async def _result(client: AsyncClient, op: dict, task: Task, outcome: str, **extra: Any) -> None:
    resp = await client.post(
        f"/api/tasks/{task.id}/result", json={"outcome": outcome, **extra}, headers=op
    )
    assert resp.status_code == 200, resp.text


async def _visit(clinic: dict, patient_id: uuid.UUID, status: AppointmentStatus, hour: int) -> None:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
    start = start.replace(hour=hour)
    async with SessionLocal() as s:
        s.add(
            Appointment(
                patient_id=patient_id, branch_id=uuid.UUID(clinic["branch"]),
                doctor_id=uuid.UUID(clinic["d1"]), starts_at=start,
                ends_at=start + timedelta(minutes=30), status=status,
            )
        )  # fmt: skip
        await s.commit()


@pytest.fixture
async def running(client: AsyncClient, sup: dict, clinic: dict, op: dict) -> dict:
    """An active campaign over 5 legacy patients with 4 calls made today:
    booked + visited, refused (price), no answer, booked (no visit yet)."""
    ids = [await patient(f"Kamp {i}", category="acne") for i in range(5)]
    body = {"name": "Akne", "segment": {"categories": ["acne"]}, "daily_limit": 4}
    created = (await client.post("/api/campaigns", json=body, headers=sup)).json()
    url = f"/api/campaigns/{created['id']}"
    await client.post(f"{url}/status", json={"status": "active"}, headers=sup)
    async with SessionLocal() as s:
        tasks = list(
            await s.scalars(
                select(Task).where(Task.type == TaskType.CAMPAIGN).order_by(Task.created_at)
            )
        )
    assert len(tasks) == 4
    await _result(client, op, tasks[0], "booked", note="Dushanba 10:00 ga yozildi")
    await _visit(clinic, tasks[0].patient_id, AppointmentStatus.COMPLETED, 9)
    await _result(
        client, op, tasks[1], "refused", reason="price", note="Qimmat dedi, +998901234567"
    )
    await _result(client, op, tasks[2], "no_answer")
    await _result(client, op, tasks[3], "booked")
    await _visit(clinic, tasks[3].patient_id, AppointmentStatus.SCHEDULED, 11)
    return {"url": url, "tasks": tasks, "ids": ids}


async def test_campaign_results_progress_and_members(
    client: AsyncClient, sup: dict, running: dict
) -> None:
    detail = (await client.get(running["url"], headers=sup)).json()
    r = detail["results"]
    assert r["calls"] == 4 and r["called"] == 4
    assert r["reached"] == 3 and r["dial_rate"] == 75.0  # no answer is not reached
    assert r["booked"] == 2 and r["arrived"] == 1 and r["arrival_rate"] == 50.0
    assert r["refusal_reasons"] == {"price": 1}
    assert r["outcomes"] == {"booked": 2, "refused": 1}  # the no-answer task is still open
    assert r["today"] == {"tasks": 4, "calls": 4}
    p = detail["progress"]
    assert p == {"audience": 5, "tasked": 4, "remaining": 1, "percent": 80.0, "days_left": 1}

    page = (await client.get(f"{running['url']}/members?limit=2", headers=sup)).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    everyone = (await client.get(f"{running['url']}/members", headers=sup)).json()["items"]
    visited = [m for m in everyone if m["arrived"]]
    assert len(visited) == 1 and visited[0]["booked"] and visited[0]["outcome"] == "booked"
    assert all(m["phone"].startswith("+99890") and m["patient_name"] for m in everyone)
    refused = (await client.get(f"{running['url']}/members?outcome=refused", headers=sup)).json()[
        "items"
    ]
    assert [m["reason"] for m in refused] == ["price"]
    still_open = (await client.get(f"{running['url']}/members?status=open", headers=sup)).json()
    assert still_open["total"] == 1 and still_open["items"][0]["attempts"] == 1


async def test_booking_long_after_the_call_is_not_credited(
    client: AsyncClient, sup: dict, running: dict, clinic: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "campaign_attribution_days", 0)  # window closed
    r = (await client.get(running["url"], headers=sup)).json()["results"]
    assert r["arrived"] == 0
    assert r["booked"] == 2  # still the operators' "booked" results


async def test_a_later_self_booking_counts_for_the_campaign(
    client: AsyncClient, sup: dict, running: dict, clinic: dict
) -> None:
    # the patient who refused calls back a few days later and books
    await _visit(clinic, running["tasks"][1].patient_id, AppointmentStatus.CONFIRMED, 13)
    r = (await client.get(running["url"], headers=sup)).json()["results"]
    assert r["booked"] == 3 and r["refusal_reasons"] == {"price": 1}
    refused = (await client.get(f"{running['url']}/members?outcome=refused", headers=sup)).json()[
        "items"
    ]
    assert refused[0]["booked"] and not refused[0]["arrived"]


async def test_campaign_list_sorts_by_status(client: AsyncClient, sup: dict) -> None:
    await patient("Aziza")
    ids = {}
    for name in ("Qoralama", "Faol", "Tugagan"):
        body = {"name": name, "segment": {}}
        ids[name] = (await client.post("/api/campaigns", json=body, headers=sup)).json()["id"]
    await client.post(
        f"/api/campaigns/{ids['Faol']}/status", json={"status": "active"}, headers=sup
    )
    await client.post(
        f"/api/campaigns/{ids['Tugagan']}/status", json={"status": "finished"}, headers=sup
    )
    names = [c["name"] for c in (await client.get("/api/campaigns", headers=sup)).json()]
    assert names == ["Faol", "Qoralama", "Tugagan"]
    only = (await client.get("/api/campaigns?status=draft", headers=sup)).json()
    assert [c["name"] for c in only] == ["Qoralama"]
    faol = next(
        c for c in (await client.get("/api/campaigns", headers=sup)).json() if c["name"] == "Faol"
    )
    assert faol["progress"]["tasked"] == 1 and faol["progress"]["days_left"] is None


# --- AI summary (TZ 4.8.3) ----------------------------------------------------------------


class FakeLlm:
    name = "fake-llm"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    async def parse(self, *, system: str, user: str, schema: type[BaseModel], cache_key: str):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.fail:
            raise LlmError("boom")
        return CampaignSummaryOut(
            summary="Akne kampaniyasi: 4 ta qo'ng'iroq, 2 ta yozuv.",
            what_worked=["Dozvon yaxshi"], problems=["Narx e'tirozi"],
            refusal_insights=["Narx qimmat"], ab_verdict=None,
            recommendations=["Aksiya taklif qiling"],
        )  # fmt: skip


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    monkeypatch.setattr("app.integrations.llm.get_llm", lambda: fake)
    return fake


async def test_ai_summary_is_masked_cached_and_refreshed_on_new_results(
    client: AsyncClient, sup: dict, running: dict, llm: FakeLlm, op: dict
) -> None:
    url = f"{running['url']}/ai-summary"
    first = await client.post(url, headers=sup)
    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    assert first.json()["content"]["recommendations"] == ["Aksiya taklif qiling"]
    sent = llm.calls[0]["user"]
    assert "+998901234567" not in sent and "Qimmat dedi" in sent  # phone masked, note kept
    assert "Kamp 0" not in sent  # no patient names

    detail = (await client.get(running["url"], headers=sup)).json()
    assert detail["ai_summary"]["summary"].startswith("Akne") and not detail["ai_summary_stale"]

    # nothing changed: the cached answer, no new request
    again = (await client.post(url, headers=sup)).json()
    assert again["cached"] is True and len(llm.calls) == 1

    # a new result makes it stale; asking again sends a new request
    await _result(client, op, running["tasks"][2], "thinking")  # the no-answer one, still open
    assert (await client.get(running["url"], headers=sup)).json()["ai_summary_stale"]
    assert (await client.post(url, headers=sup)).json()["cached"] is False
    assert len(llm.calls) == 2
    async with SessionLocal() as s:
        logs = list(
            await s.scalars(select(AuditLog).where(AuditLog.action == "campaign.ai_summary"))
        )
    assert len(logs) == 2


async def test_ai_summary_errors(
    client: AsyncClient, sup: dict, running: dict, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"{running['url']}/ai-summary"
    llm.fail = True
    failed = await client.post(url, headers=sup)
    assert failed.status_code == 502 and failed.json()["detail"] == "ai_failed"

    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    off = await client.post(url, headers=sup)
    assert off.status_code == 503 and off.json()["detail"] == "ai_disabled"


async def test_ai_summary_needs_calls(client: AsyncClient, sup: dict, llm: FakeLlm) -> None:
    await patient("Aziza")
    created = (
        await client.post("/api/campaigns", json={"name": "Bo'sh", "segment": {}}, headers=sup)
    ).json()
    resp = await client.post(f"/api/campaigns/{created['id']}/ai-summary", headers=sup)
    assert resp.status_code == 400 and resp.json()["detail"] == "no_results"
    assert llm.calls == []


async def test_attempts_are_the_calls_not_automatic_closures(
    client: AsyncClient, sup: dict, running: dict
) -> None:
    async with SessionLocal() as s:
        attempts = list(await s.scalars(select(TaskAttempt)))
    assert len(attempts) == 4 and not any(a.automatic for a in attempts)
