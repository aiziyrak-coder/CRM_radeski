"""Dashboards, KPI filters and time series, the QA panel and the call log (TZ 1.1, 4.7, 4.8,
4.11). Data is written straight into the tables: these tests are about the figures."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.ai import router as ai_router
from app.modules.ai.models import AiDigest, AnalysisStatus, CallAnalysis, QaCriterion
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Branch, Doctor, ServiceCategory
from app.modules.diagnoses.models import DiagnosisMapping, MappingStatus
from app.modules.leads.models import Lead, LeadChannel, LeadStage
from app.modules.patients.models import Source
from app.modules.scheduling.models import Appointment, AppointmentService, AppointmentStatus
from app.modules.tasks.models import Outcome, Task, TaskStatus, TaskType
from app.modules.telephony.models import Call, CallDirection, CallStatus, RecordingStatus
from app.modules.users.models import Role, User
from tests.conftest import bearer, login, make_user

S = AppointmentStatus
TODAY = clinic_time.today()
D = TODAY - timedelta(days=3)  # a finished day: every visit on it is in the past


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return clinic_time.at(day, time(hh, mm))


async def user_id(username: str) -> uuid.UUID:
    async with SessionLocal() as s:
        return (await s.scalars(select(User.id).where(User.username == username))).one()


async def add(*rows: Any) -> None:
    async with SessionLocal() as s:
        s.add_all(rows)
        await s.commit()


def appointment(
    c: dict, starts: datetime, *, status: S, branch: str | None = None, doctor: str = "d1",
    service: str = "consult", source: Source | None = None, by: uuid.UUID | None = None,
    created: datetime | None = None,
) -> Appointment:  # fmt: skip
    return Appointment(
        patient_id=uuid.UUID(c["patient"]),
        branch_id=uuid.UUID(branch or c["branch"]),
        doctor_id=uuid.UUID(c[doctor]),
        starts_at=starts,
        ends_at=starts + timedelta(minutes=30),
        status=status,
        source=source,
        created_by=by,
        created_at=created or starts - timedelta(hours=1),
        services=[AppointmentService(service_id=uuid.UUID(c[service]), duration_min=30)],
    )


def call(
    started: datetime, *, direction: CallDirection = CallDirection.IN,
    status: CallStatus = CallStatus.ANSWERED, phone: str | None = "+998901112233",
    user: uuid.UUID | None = None, **extra: Any,
) -> Call:  # fmt: skip
    return Call(
        pbx_id=str(uuid.uuid4()),
        direction=direction,
        status=status,
        phone=phone,
        started_at=started,
        ended_at=started + timedelta(minutes=2),
        user_id=user,
        **extra,
    )


def analysis(c: Call, score: int, **extra: Any) -> CallAnalysis:
    return CallAnalysis(call_id=c.id, status=AnalysisStatus.READY, attempts=1, score=score, **extra)


async def manager(client: AsyncClient, role: Role = Role.OWNER, name: str = "boss") -> dict:
    await make_user(name, role)
    return bearer(await login(client, name))


# --- KPI --------------------------------------------------------------------------------------


@pytest.fixture
async def period_data(clinic: dict) -> dict:
    """Day D: three bookings in two branches, two inquiries, missed calls and QA scores."""
    await make_user("op1", Role.OPERATOR)
    await make_user("op2", Role.OPERATOR)
    op1, op2 = await user_id("op1"), await user_id("op2")
    async with SessionLocal() as s:
        kokand = Branch(name_uz="Qo'qon", name_ru="Коканд")
        s.add(kokand)
        await s.flush()
        cosm = (
            await s.scalars(select(ServiceCategory.id).where(ServiceCategory.site_id == "laser"))
        ).one()
        await s.commit()
    a1 = appointment(clinic, at(D, 10), status=S.ARRIVED, source=Source.INSTAGRAM, by=op1)
    a2 = appointment(
        clinic, at(D, 10), status=S.NO_SHOW, doctor="d2", service="laser",
        source=Source.GOOGLE, by=op2,
    )  # fmt: skip
    a3 = appointment(
        clinic, at(D, 12), status=S.COMPLETED, branch=str(kokand.id),
        source=Source.INSTAGRAM, by=op1,
    )  # fmt: skip
    # booked the day before D (the previous period of a one-day KPI)
    a4 = appointment(
        clinic, at(D, 15), status=S.CANCELLED, by=op1, created=at(D - timedelta(days=1), 11)
    )
    await add(a1, a2, a3, a4)
    await add(
        Lead(
            phone="+998901112233", channel=LeadChannel.WEBSITE, source=Source.INSTAGRAM,
            created_at=at(D, 9), sla_due_at=at(D, 9, 15), first_response_at=at(D, 9, 10),
            appointment_id=a1.id, stage=LeadStage.VISITED,
        ),
        Lead(
            phone="+998901112244", channel=LeadChannel.TELEGRAM, source=Source.GOOGLE,
            created_at=at(D, 9, 30), sla_due_at=at(D, 9, 45),
        ),
    )  # fmt: skip
    missed = call(at(D, 10), status=CallStatus.MISSED)
    back = call(at(D, 10, 30), direction=CallDirection.OUT, user=op1, talk_seconds=60)
    never = call(at(D, 11), status=CallStatus.ABANDONED, phone="+998901119999")
    anonymous = call(at(D, 11, 5), status=CallStatus.MISSED, phone=None, caller_raw="anonymous")
    scored1 = call(at(D, 13), user=op1, phone="+998901110000", talk_seconds=120)
    scored2 = call(at(D, 14), user=op2, phone="+998901110001", talk_seconds=90)
    await add(missed, back, never, anonymous, scored1, scored2)
    await add(analysis(scored1, 80), analysis(scored2, 60))
    return {
        "op1": op1, "op2": op2, "kokand": kokand.id, "cosm": cosm, "a1": a1.id,
        "missed": missed.id, "back": back.id,
    }  # fmt: skip


async def kpi(client: AsyncClient, headers: dict, **params: Any) -> dict:
    resp = await client.get(
        "/api/reports/kpi", params={"from": D, "to": D, **params}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_kpi_filters(client: AsyncClient, clinic: dict, period_data: dict) -> None:
    owner = await manager(client)
    k = await kpi(client, owner)
    assert (k["bookings"], k["visits"], k["booking_to_visit"], k["no_show_rate"]) == (
        3, 2, 66.7, 33.3,
    )  # fmt: skip
    assert k["leads_total"] == 2 and k["lead_to_booking"] == 50.0 and k["leads_handled"] == 1
    assert k["first_response_median_min"] == 10.0

    # branch and service direction narrow the appointment figures
    k = await kpi(client, owner, branch_id=clinic["branch"])
    assert (k["bookings"], k["no_show_rate"]) == (2, 50.0)
    k = await kpi(client, owner, category_id=period_data["cosm"])
    assert (k["bookings"], k["no_show_rate"]) == (1, 100.0)
    # source: inquiries and appointments
    k = await kpi(client, owner, source="instagram")
    assert (k["bookings"], k["no_show_rate"], k["leads_total"], k["lead_to_booking"]) == (
        2, 0.0, 1, 100.0,
    )  # fmt: skip
    # operator: their bookings, calls and QA score
    k = await kpi(client, owner, user_id=period_data["op1"])
    assert k["bookings"] == 2 and k["qa_score"] == 80 and k["outbound_calls"] == 1
    assert [o["name"] for o in k["operators"]] == ["Op1"]
    assert (await client.get(
        "/api/reports/kpi", params={"from": D, "to": D, "source": "tv"}, headers=owner
    )).status_code == 422  # fmt: skip


async def test_kpi_missed_callbacks_qa_and_leaderboard(
    client: AsyncClient, clinic: dict, period_data: dict
) -> None:
    owner = await manager(client)
    k = await kpi(client, owner)
    # TZ 4.11: missed calls and how fast they were called back (the anonymous one can't be)
    assert k["missed_total"] == 3 and k["missed_called_back"] == 1
    assert k["missed_not_called_back"] == 1 and k["missed_callback_avg_min"] == 30.0
    assert k["qa_score"] == 70 and k["qa_analysed"] == 2
    board = {o["name"]: o for o in k["operators"]}
    assert board["Op1"]["appointments_created"] == 2 and board["Op1"]["qa_score"] == 80
    assert board["Op2"]["qa_score"] == 60 and board["Op2"]["appointments_created"] == 1
    assert k["operators"][0]["name"] == "Op1"  # most bookings first


async def test_kpi_compares_with_the_previous_period(
    client: AsyncClient, clinic: dict, period_data: dict
) -> None:
    owner = await manager(client)
    k = await kpi(client, owner, compare=True)
    prev = k["previous"]
    assert prev["from"] == prev["to"] == (D - timedelta(days=1)).isoformat()
    assert prev["bookings"] == 1 and prev["leads_total"] == 0 and k["bookings"] == 3
    assert "operators" not in prev
    week = (
        await client.get(
            "/api/reports/kpi",
            params={"from": D - timedelta(days=6), "to": D, "compare": True},
            headers=owner,
        )
    ).json()
    assert week["previous"]["to"] == (D - timedelta(days=7)).isoformat()
    assert week["previous"]["from"] == (D - timedelta(days=13)).isoformat()


async def test_reports_access(client: AsyncClient, clinic: dict, op: dict) -> None:
    params = {"from": D, "to": D}
    for path in ("/api/reports/kpi", "/api/reports/series"):
        assert (await client.get(path, params=params, headers=op)).status_code == 403
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    assert (await client.get("/api/reports/series", params=params, headers=sup)).status_code == 200
    bad = {"from": D, "to": D - timedelta(days=1)}
    assert (await client.get("/api/reports/series", params=bad, headers=sup)).status_code == 400


# --- series -----------------------------------------------------------------------------------


async def test_series_days_sources_and_funnel(
    client: AsyncClient, clinic: dict, period_data: dict
) -> None:
    # 01:00 in Tashkent is the previous day in UTC: it must still count on its local day
    early = at(D - timedelta(days=1), 1)
    assert early.astimezone(UTC).date() == D - timedelta(days=2)
    await add(Lead(phone="+998901115555", channel=LeadChannel.MANUAL, created_at=early,
                   sla_due_at=early))  # fmt: skip
    owner = await manager(client)
    resp = await client.get(
        "/api/reports/series", params={"from": D - timedelta(days=1), "to": D}, headers=owner
    )
    data = resp.json()
    before, day = data["days"]
    assert before["date"] == (D - timedelta(days=1)).isoformat() and before["leads"] == 1
    assert before["bookings"] == 1
    assert (day["leads"], day["bookings"], day["visits"], day["no_shows"]) == (2, 3, 2, 1)
    assert (day["calls_in"], day["calls_out"], day["calls_missed"]) == (5, 1, 3)
    assert day["qa_score"] == 70 and before["qa_score"] is None
    sources = {r["source"]: r for r in data["sources"]}
    assert sources["instagram"]["booked"] == 1 and sources["instagram"]["conversion"] == 100.0
    assert sources["google"]["leads"] == 1 and sources["unknown"]["leads"] == 1
    funnel = [(f["stage"], f["count"]) for f in data["funnel"]]
    assert funnel == [
        ("new", 3), ("contacted", 1), ("booked", 1), ("confirmed", 1), ("visited", 1),
    ]  # fmt: skip

    # filters reach the series too
    only = (
        await client.get(
            "/api/reports/series",
            params={"from": D, "to": D, "user_id": str(period_data["op2"])},
            headers=owner,
        )
    ).json()["days"][0]
    assert only["bookings"] == 1 and only["qa_score"] == 60 and only["calls_out"] == 0


# --- daily report -----------------------------------------------------------------------------


async def test_daily_filters_scope_and_export(
    client: AsyncClient, clinic: dict, period_data: dict
) -> None:
    owner = await manager(client)
    params = {"date": D.isoformat()}
    full = (await client.get("/api/reports/daily", params=params, headers=owner)).json()
    assert full["booked"] == 3 and full["no_shows"] == 1 and full["new_leads"] == 2
    branch = (
        await client.get(
            "/api/reports/daily",
            params={**params, "branch_id": clinic["branch"], "source": "google"},
            headers=owner,
        )
    ).json()
    assert branch["booked"] == 1 and branch["no_shows"] == 1 and branch["new_leads"] == 1

    # an operator always gets their own day, whatever user_id they send
    op1 = bearer(await login(client, "op1"))
    mine = (
        await client.get(
            "/api/reports/daily",
            params={**params, "user_id": str(period_data["op2"])},
            headers=op1,
        )
    ).json()
    assert mine["filters"]["user_id"] == str(period_data["op1"]) and mine["booked"] == 2

    xlsx = await client.get(
        "/api/reports/daily.xlsx",
        params={**params, "user_id": str(period_data["op1"])},
        headers=owner,
    )
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    async with SessionLocal() as s:
        row = await s.scalar(select(AuditLog).where(AuditLog.entity == "daily"))
    assert row.action == "report.export" and row.after["user_id"] == str(period_data["op1"])
    await make_user("reg1", Role.REGISTRAR)
    reg = bearer(await login(client, "reg1"))
    assert (await client.get("/api/reports/daily", headers=reg)).status_code == 403


# --- QA panel ---------------------------------------------------------------------------------


@pytest.fixture
async def qa_data(clinic: dict) -> dict:
    await make_user("op1", Role.OPERATOR)
    await make_user("op2", Role.OPERATOR)
    op1, op2 = await user_id("op1"), await user_id("op2")
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)  # last week's Monday
    c1 = call(at(monday, 10), user=op1, patient_id=uuid.UUID(clinic["patient"]))
    c2 = call(at(monday + timedelta(days=1), 10), user=op2)
    c3 = call(at(monday + timedelta(days=7), 10), user=op1)
    await add(c1, c2, c3)
    await add(
        analysis(
            c1, 50,
            criteria=[{"code": "greeting", "passed": False}, {"code": "need", "passed": True}],
            violations=[{"criterion": "greeting", "quote": "Allo", "at": 1.5}],
            red_flags=[{"code": "diagnosis", "quote": "bu akne", "at": 20.0}],
            has_red_flags=True,
        ),
        analysis(
            c2, 90,
            criteria=[{"code": "greeting", "passed": True}, {"code": "need", "passed": None}],
            violations=[],
        ),
        analysis(
            c3, 70,
            criteria=[{"code": "greeting", "passed": True}],
            violations=[{"criterion": "two_slots", "quote": "qachon xohlaysiz?", "at": 33.0}],
        ),
    )  # fmt: skip
    return {"op1": op1, "op2": op2, "monday": monday, "c1": c1.id, "c2": c2.id, "c3": c3.id}


async def test_qa_trend_by_day_week_and_operator(client: AsyncClient, qa_data: dict) -> None:
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    monday = qa_data["monday"]
    params = {"from": monday, "to": monday + timedelta(days=13)}
    days = (await client.get("/api/ai/qa/trend", params=params, headers=sup)).json()
    assert len(days["points"]) == 14 and days["points"][0]["avg_score"] == 50
    assert days["points"][2] == {"start": (monday + timedelta(days=2)).isoformat(), "calls": 0,
                                 "avg_score": None}  # fmt: skip
    weeks = (
        await client.get("/api/ai/qa/trend", params={**params, "bucket": "week"}, headers=sup)
    ).json()
    assert [p["avg_score"] for p in weeks["points"]] == [70, 70]
    assert [p["calls"] for p in weeks["points"]] == [2, 1]
    greeting = next(c for c in weeks["criteria"] if c["code"] == "greeting")
    assert [p["pass_rate"] for p in greeting["points"]] == [50, 100]
    need = next(c for c in weeks["criteria"] if c["code"] == "need")
    assert need["points"][0]["applicable"] == 1  # "not applicable" doesn't count
    op1 = next(o for o in weeks["operators"] if o["user_id"] == str(qa_data["op1"]))
    assert [p["avg_score"] for p in op1["points"]] == [50, 70]
    one = (
        await client.get(
            "/api/ai/qa/trend",
            params={**params, "bucket": "week", "user_id": str(qa_data["op2"])},
            headers=sup,
        )
    ).json()
    assert [p["avg_score"] for p in one["points"]] == [90, None]


async def test_qa_violations_list(client: AsyncClient, qa_data: dict) -> None:
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    params = {"from": qa_data["monday"], "to": TODAY}
    data = (await client.get("/api/ai/qa/violations", params=params, headers=sup)).json()
    assert data["total"] == 3 and data["counts"] == {"greeting": 1, "diagnosis": 1, "two_slots": 1}
    first = data["items"][0]  # newest first
    assert first["code"] == "two_slots" and first["at"] == 33.0 and first["user_name"] == "Op1"
    flags = (
        await client.get(
            "/api/ai/qa/violations", params={**params, "kind": "red_flag"}, headers=sup
        )
    ).json()
    assert [(i["kind"], i["quote"], i["reviewed"]) for i in flags["items"]] == [
        ("red_flag", "bu akne", False)
    ]
    greeting = (
        await client.get(
            "/api/ai/qa/violations", params={**params, "code": "greeting"}, headers=sup
        )
    ).json()
    assert greeting["total"] == 1 and greeting["items"][0]["patient_name"] == "Sinov Bemor"
    page = (
        await client.get(
            "/api/ai/qa/violations", params={**params, "limit": 1, "offset": 1}, headers=sup
        )
    ).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    op = bearer(await login(client, "op1"))
    assert (await client.get("/api/ai/qa/violations", headers=op)).status_code == 403


async def test_qa_queue_and_retry(
    client: AsyncClient, clinic: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user("op1", Role.OPERATOR)
    rec = {"recording": "x.mp3", "recording_status": RecordingStatus.READY}
    fresh = call(at(D, 9), **rec)
    failed = call(at(D, 10), **rec)
    done = call(at(D, 11), **rec)
    no_recording = call(at(D, 12))
    await add(fresh, failed, done, no_recording)
    await add(
        CallAnalysis(call_id=failed.id, status=AnalysisStatus.FAILED, attempts=3, error="boom"),
        analysis(done, 80),
    )
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    params = {"from": D, "to": D}
    q = (await client.get("/api/ai/qa/queue", params=params, headers=sup)).json()
    assert q["total"] == 2 and q["counts"] == {"missing": 1, "failed": 1}
    assert {i["call_id"] for i in q["items"]} == {str(fresh.id), str(failed.id)}

    body = {"call_ids": [str(failed.id), str(done.id), str(fresh.id), str(failed.id)]}
    # without an API key there is nothing to retry with
    assert (await client.post("/api/ai/qa/retry", json=body, headers=sup)).status_code == 409
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(ai_router, "_enqueue_analysis", queued.append)
    resp = await client.post("/api/ai/qa/retry", json=body, headers=sup)
    assert resp.json() == {"queued": 2, "skipped": 1}
    assert set(queued) == {failed.id, fresh.id}
    async with SessionLocal() as s:
        a = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == failed.id))
    assert (a.status, a.attempts, a.error) == (AnalysisStatus.PENDING, 0, None)
    owner = await manager(client)
    assert (await client.post("/api/ai/qa/retry", json=body, headers=owner)).status_code == 403


async def test_supervisor_adds_a_criterion(client: AsyncClient) -> None:
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    body = {
        "name_uz": "Narxni aytdi", "name_ru": "Назвал цену",
        "description": "Told the price range when asked.", "weight": 10, "active": True,
    }  # fmt: skip
    first = await client.post("/api/ai/criteria", json=body, headers=sup)
    assert first.status_code == 201 and first.json()["code"] == "narxni_aytdi"
    second = (await client.post("/api/ai/criteria", json=body, headers=sup)).json()
    assert second["code"] == "narxni_aytdi_2"
    codes = [c["code"] for c in (await client.get("/api/ai/criteria", headers=sup)).json()]
    assert codes[0] == "greeting" and codes[-2:] == ["narxni_aytdi", "narxni_aytdi_2"]
    owner = await manager(client)
    assert (await client.post("/api/ai/criteria", json=body, headers=owner)).status_code == 403
    async with SessionLocal() as s:
        assert await s.scalar(select(QaCriterion).where(QaCriterion.code == "narxni_aytdi"))


async def test_digest_history(client: AsyncClient) -> None:
    old = AiDigest(
        period_from=D - timedelta(days=13), period_to=D - timedelta(days=7),
        stats={"calls_analysed": 4, "avg_score": 75}, content=None,
        created_at=datetime.now(UTC) - timedelta(days=7),
    )  # fmt: skip
    new = AiDigest(
        period_from=D - timedelta(days=6), period_to=D, stats={"calls_analysed": 9},
        content={"summary": "ok"}, created_at=datetime.now(UTC),
    )  # fmt: skip
    await add(old, new)
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    items = (await client.get("/api/ai/digests", headers=sup)).json()
    assert [i["id"] for i in items] == [str(new.id), str(old.id)]
    assert items[0]["has_content"] and items[1]["avg_score"] == 75
    one = (await client.get(f"/api/ai/digests/{old.id}", headers=sup)).json()
    assert one["stats"]["calls_analysed"] == 4
    missing = await client.get(f"/api/ai/digests/{uuid.uuid4()}", headers=sup)
    assert missing.status_code == 404


# --- call log ---------------------------------------------------------------------------------


async def test_call_log_filters_search_pages_and_results(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    op1 = await user_id("op1")
    await make_user("op2", Role.OPERATOR)
    op2 = await user_id("op2")
    patient = uuid.UUID(clinic["patient"])
    task = Task(
        type=TaskType.CONFIRM_VISIT, status=TaskStatus.DONE, priority=1, due_at=at(D, 9),
        created_at=at(D, 8), patient_id=patient, outcome=Outcome.REFUSED,
        outcome_reason="price",
    )  # fmt: skip
    await add(task)
    missed = call(at(D, 9), status=CallStatus.MISSED, phone="+998901234567", wait_seconds=40)
    back = call(at(D, 9, 20), direction=CallDirection.OUT, phone="+998901234567", user=op1)
    talk = call(
        at(D, 10), user=op1, patient_id=patient, phone="+998900000001", task_id=task.id,
        wait_seconds=10, talk_seconds=180,
    )  # fmt: skip
    other = call(at(D, 11), user=op2, phone="+998907777777", talk_seconds=60)
    yesterday = call(at(D - timedelta(days=1), 12), user=op2, phone="+998907777777")
    await add(missed, back, talk, other, yesterday)
    await add(analysis(talk, 85, suggested_outcome="booked"))

    params = {"from": D, "to": D}
    page = (await client.get("/api/telephony/call-log", params=params, headers=op)).json()
    assert page["total"] == 4 and [i["id"] for i in page["items"]][0] == str(other.id)
    s = page["summary"]
    assert (s["inbound"], s["outbound"], s["answered"], s["missed"]) == (3, 1, 2, 1)
    assert s["missed_not_called_back"] == 0 and s["avg_wait_sec"] == 25 and s["talk_minutes"] == 4
    items = {i["id"]: i for i in page["items"]}
    assert items[str(missed.id)]["called_back_at"] is not None
    assert items[str(back.id)]["called_back_at"] is None  # only missed calls carry it
    row = items[str(talk.id)]
    assert (row["task_type"], row["task_outcome"], row["task_outcome_reason"]) == (
        "confirm_visit", "refused", "price",
    )  # fmt: skip
    assert row["ai_outcome"] == "booked" and row["ai_score"] == 85

    async def ids(**extra: Any) -> list[str]:
        resp = await client.get("/api/telephony/call-log", params={**params, **extra}, headers=op)
        assert resp.status_code == 200, resp.text
        return [i["id"] for i in resp.json()["items"]]

    assert await ids(user_id=str(op2)) == [str(other.id)]
    assert await ids(who="mine") == [str(talk.id), str(back.id)]
    assert await ids(status="unanswered") == [str(missed.id)]
    assert await ids(direction="out") == [str(back.id)]
    assert await ids(q="90 123 45") == [str(back.id), str(missed.id)]  # part of the number
    assert await ids(q="Синов") == [str(talk.id)]  # Cyrillic finds the Latin name
    assert await ids(limit=2, offset=2) == [str(back.id), str(missed.id)]
    wide = await ids(**{"from": D - timedelta(days=1)})
    assert str(yesterday.id) in wide and len(wide) == 5
    too_wide = {"from": D - timedelta(days=200), "to": D}
    assert (
        await client.get("/api/telephony/call-log", params=too_wide, headers=op)
    ).status_code == 400
    await make_user("doc1", Role.DOCTOR)
    doc = bearer(await login(client, "doc1"))
    assert (await client.get("/api/telephony/call-log", headers=doc)).status_code == 403


# --- setup checklist and today's visits -------------------------------------------------------


async def test_setup_checklist(client: AsyncClient, clinic: dict) -> None:
    admin = await manager(client, Role.ADMIN, "admin1")
    data = (await client.get("/api/system/setup", headers=admin)).json()
    rows = {i["key"]: i for i in data["items"]}
    assert rows["catalog"]["status"] == "todo"  # nothing came from the site yet
    assert (rows["doctor_schedules"]["done"], rows["doctor_schedules"]["total"]) == (2, 3)
    assert rows["doctor_schedules"]["status"] == "partial"
    assert rows["doctor_accounts"]["status"] == "todo"
    assert rows["resources"]["status"] == "ok" and rows["resources"]["devices"] == 1
    assert (rows["service_durations"]["done"], rows["service_durations"]["total"]) == (1, 2)
    assert rows["users"]["status"] == "todo" and rows["users"]["roles"]["operator"] == 0
    assert rows["legacy_import"]["status"] == "ok" and rows["legacy_import"]["legacy"] == 1
    assert rows["ai"]["status"] == "off" and rows["diagnoses"]["status"] == "todo"
    assert all(i["link"] is None or i["link"].startswith("/") for i in data["items"])

    # fixing things turns rows green
    async with SessionLocal() as s:
        audit.record(
            s, "catalog.service", entity="service", entity_id=clinic["consult"],
            after={"duration_min": 30},
        )  # fmt: skip
        doctor = await s.get(Doctor, uuid.UUID(clinic["d1"]))
        doctor.user_id = await s.scalar(select(User.id).where(User.username == "admin1"))
        s.add(DiagnosisMapping(text="akne", status=MappingStatus.APPROVED, category_code="acne"))
        await s.commit()
    await make_user("op1", Role.OPERATOR)
    rows = {
        i["key"]: i for i in (await client.get("/api/system/setup", headers=admin)).json()["items"]
    }
    assert rows["service_durations"]["status"] == "ok"
    assert rows["doctor_accounts"]["status"] == "partial"
    assert rows["diagnoses"]["status"] == "ok"
    assert rows["users"]["status"] == "partial" and rows["users"]["roles"]["operator"] == 1
    sup = await manager(client, Role.SUPERVISOR, "sup1")
    assert (await client.get("/api/system/setup", headers=sup)).status_code == 403


async def test_today_for_registrar_and_doctor(client: AsyncClient, clinic: dict) -> None:
    async with SessionLocal() as s:
        kokand = Branch(name_uz="Qo'qon", name_ru="Коканд")
        s.add(kokand)
        await s.commit()
    now = clinic_time.now()
    await add(
        appointment(clinic, now - timedelta(hours=3), status=S.ARRIVED),
        appointment(clinic, now + timedelta(hours=2), status=S.CONFIRMED, doctor="d2"),
        appointment(clinic, now - timedelta(hours=5), status=S.CANCELLED, doctor="d2"),
        appointment(clinic, now + timedelta(hours=1), status=S.SCHEDULED, branch=str(kokand.id)),
    )
    if any(clinic_time.local(now + timedelta(hours=h)).date() != TODAY for h in (-5, 2)):
        pytest.skip("run too close to midnight for 'today' to hold every visit")
    await make_user("reg1", Role.REGISTRAR)
    async with SessionLocal() as s:
        reg = (await s.scalars(select(User).where(User.username == "reg1"))).one()
        reg.branch_id = uuid.UUID(clinic["branch"])
        await s.commit()
    headers = bearer(await login(client, "reg1"))
    data = (await client.get("/api/system/today", headers=headers)).json()
    assert data["scope"] == "branch" and data["branch_id"] == clinic["branch"]
    c = data["counts"]
    assert (c["total"], c["came"], c["expected"], c["cancelled"]) == (2, 1, 1, 1)
    assert data["next_at"] is not None

    await make_user("doc1", Role.DOCTOR)
    doc = bearer(await login(client, "doc1"))
    unlinked = (await client.get("/api/system/today", headers=doc)).json()
    assert unlinked["linked"] is False and unlinked["counts"]["total"] == 0
    async with SessionLocal() as s:
        doctor = await s.get(Doctor, uuid.UUID(clinic["d2"]))
        doctor.user_id = await user_id("doc1")
        await s.commit()
    mine = (await client.get("/api/system/today", headers=doc)).json()
    assert mine["linked"] and mine["counts"]["total"] == 1 and mine["counts"]["expected"] == 1
