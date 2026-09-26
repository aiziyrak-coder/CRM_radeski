"""Task rules, lead stages, campaigns and reports: fixes of the phase 2 review."""

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core import clinic_time, events
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import emit
from app.modules.campaigns import service as campaigns
from app.modules.campaigns.models import Campaign, CampaignStatus
from app.modules.catalog.models import Service
from app.modules.leads.models import Lead
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.scheduling.models import Appointment, AppointmentStatus
from app.modules.tasks import service as tasks
from app.modules.tasks.models import TASK_DEFAULTS, Outcome, Task, TaskAttempt, TaskStatus, TaskType
from app.modules.telephony.models import Call, CallDirection, CallStatus
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import at, booking, next_monday

S = AppointmentStatus


async def tasks_of(type_: TaskType, status: TaskStatus | None = TaskStatus.OPEN) -> list[Task]:
    async with SessionLocal() as s:
        stmt = select(Task).where(Task.type == type_)
        if status:
            stmt = stmt.where(Task.status == status)
        return list(await s.scalars(stmt.order_by(Task.created_at)))


async def call_event(
    *,
    pbx_id: str,
    status: CallStatus,
    phone: str | None,
    patient_id: str | None = None,
    lead_id: uuid.UUID | None = None,
    callback: bool = False,
) -> uuid.UUID:
    """What the telephony module does at the end of an inbound call."""
    async with SessionLocal() as s:
        call = await s.scalar(select(Call).where(Call.pbx_id == pbx_id))
        if call is None:
            call = Call(
                pbx_id=pbx_id, direction=CallDirection.IN, status=status, phone=phone,
                patient_id=uuid.UUID(patient_id) if patient_id else None, lead_id=lead_id,
                started_at=clinic_time.now(), callback_requested=callback,
            )  # fmt: skip
            s.add(call)
            await s.flush()
        await emit(s, "call.finished", call=call)
        await s.commit()
        return call.id


@pytest.fixture
async def sup(client: AsyncClient) -> dict:
    await make_user("sup1", Role.SUPERVISOR)
    return bearer(await login(client, "sup1"))


# --- missed calls -----------------------------------------------------------------------------


async def test_missed_call_after_the_callback_was_done_gets_a_new_task(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    patient = clinic["patient"]
    await call_event(
        pbx_id="1.1", status=CallStatus.MISSED, phone="+998900000001", patient_id=patient
    )
    await call_event(
        pbx_id="1.2", status=CallStatus.ABANDONED, phone="+998900000001", patient_id=patient,
        callback=True,
    )  # fmt: skip
    [first] = await tasks_of(TaskType.MISSED_CALL)
    assert "1 ni bosib" in (first.note or "")  # the second call's request is kept on the task

    resp = await client.post(f"/api/tasks/{first.id}/result", json={"outcome": "done"}, headers=op)
    assert resp.status_code == 200
    # the same day the patient misses the clinic again: a new callback is due
    await call_event(
        pbx_id="1.3", status=CallStatus.MISSED, phone="+998900000001", patient_id=patient
    )
    [second] = await tasks_of(TaskType.MISSED_CALL)
    assert second.id != first.id
    # a re-sent event of the same call doesn't create anything
    await call_event(
        pbx_id="1.3", status=CallStatus.MISSED, phone="+998900000001", patient_id=patient
    )
    resp = await client.post(f"/api/tasks/{second.id}/result", json={"outcome": "done"}, headers=op)
    await call_event(
        pbx_id="1.3", status=CallStatus.MISSED, phone="+998900000001", patient_id=patient
    )
    assert await tasks_of(TaskType.MISSED_CALL) == []
    assert len(await tasks_of(TaskType.MISSED_CALL, None)) == 2


async def test_answered_call_resolves_the_inquiry_calls(client: AsyncClient, op: dict) -> None:
    lead = (
        await client.post("/api/leads", json={"phone": "900001234", "name": "Yangi"}, headers=op)
    ).json()
    lead_id = uuid.UUID(lead["id"])
    await call_event(pbx_id="2.1", status=CallStatus.MISSED, phone="+998900001234", lead_id=lead_id)
    # the open "new inquiry" task is that callback: one task in the queue, marked urgent
    assert await tasks_of(TaskType.MISSED_CALL) == []
    [inquiry] = await tasks_of(TaskType.NEW_LEAD)
    assert "Yana qo'ng'iroq qildi" in (inquiry.note or "")

    # the person calls again and an operator answers (no patient card yet)
    await call_event(pbx_id="2.2", status=CallStatus.ANSWERED, phone="+998900001234")
    assert await tasks_of(TaskType.MISSED_CALL) == []
    assert await tasks_of(TaskType.NEW_LEAD) == []
    async with SessionLocal() as s:
        stored = await s.get(Lead, lead_id)
    assert stored.stage == "contacted" and stored.first_response_at is not None


# --- results ----------------------------------------------------------------------------------


async def _callback_task(client: AsyncClient, op: dict, clinic: dict) -> str:
    resp = await client.post(
        "/api/tasks",
        json={"patient_id": clinic["patient"], "due_at": datetime.now(UTC).isoformat()},
        headers=op,
    )
    assert resp.json() == {"created": True}
    return str((await tasks_of(TaskType.CALLBACK))[0].id)


async def test_concurrent_results_are_recorded_once(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    task_id = await _callback_task(client, op, clinic)
    url = f"/api/tasks/{task_id}/result"
    responses = await asyncio.gather(
        *(client.post(url, json={"outcome": "done"}, headers=op) for _ in range(3))
    )
    assert sorted(r.status_code for r in responses) == [200, 400, 400]
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(TaskAttempt)) == 1


def spy_on(monkeypatch: pytest.MonkeyPatch, event: str) -> list[dict[str, Any]]:
    """Collects the payloads of a domain event for one test."""
    seen: list[dict[str, Any]] = []

    async def spy(_s: Any, p: dict[str, Any]) -> None:
        seen.append(p)

    monkeypatch.setitem(events._handlers, event, [*events._handlers[event], spy])
    return seen


async def test_no_answer_ladder_counts_only_unanswered_attempts(
    client: AsyncClient, clinic: dict, op: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = spy_on(monkeypatch, "task.result")

    task_id = await _callback_task(client, op, clinic)
    url = f"/api/tasks/{task_id}/result"
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    first = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert first["no_answer_count"] == 1
    # got through, the patient asked to call later: the ladder starts over
    moved = await client.post(url, json={"outcome": "callback", "callback_at": later}, headers=op)
    assert moved.json()["no_answer_count"] == 0
    for n in (1, 2):
        body = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
        assert body["status"] == "open" and body["no_answer_count"] == n
    assert body["attempts"] == 4
    third = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert third["status"] == "done" and third["outcome"] == "no_answer"
    assert [p["no_answer_count"] for p in results] == [1, 0, 1, 2, 3]


async def test_retry_settings_and_priorities(
    client: AsyncClient, clinic: dict, op: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TZ 4.5: today's confirmations and missed calls first, then new inquiries
    prio = {t: p for t, (p, _) in TASK_DEFAULTS.items()}
    assert prio[TaskType.CONFIRM_VISIT] < prio[TaskType.NEW_LEAD]
    assert prio[TaskType.MISSED_CALL] < prio[TaskType.NEW_LEAD]
    assert prio[TaskType.NEW_LEAD] < prio[TaskType.NO_SHOW] < prio[TaskType.REPEAT_VISIT]
    assert max(prio.values()) == prio[TaskType.CAMPAIGN]

    monkeypatch.setattr(get_settings(), "task_max_no_answer", 2)
    task_id = await _callback_task(client, op, clinic)
    url = f"/api/tasks/{task_id}/result"
    await client.post(url, json={"outcome": "no_answer"}, headers=op)
    second = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert second["status"] == "done"


# --- lead stages ------------------------------------------------------------------------------


async def test_lead_stage_goes_through_the_service(
    client: AsyncClient, op: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = spy_on(monkeypatch, "lead.stage_changed")

    lost = (await client.post("/api/leads", json={"phone": "900001111"}, headers=op)).json()
    url = f"/api/leads/{lost['id']}"
    assert (await client.patch(url, json={"stage": "lost"}, headers=op)).json()[
        "detail"
    ] == "reason_required"
    bad = await client.patch(url, json={"stage": "lost", "lost_reason": "nope"}, headers=op)
    assert bad.status_code == 400 and bad.json()["detail"] == "unknown_reason"
    ok = await client.patch(url, json={"stage": "lost", "lost_reason": "price"}, headers=op)
    assert ok.status_code == 200 and ok.json()["stage"] == "lost"
    [cancelled] = await tasks_of(TaskType.NEW_LEAD, TaskStatus.CANCELLED)
    assert str(cancelled.lead_id) == lost["id"]

    booked = (await client.post("/api/leads", json={"phone": "900002222"}, headers=op)).json()
    resp = await client.patch(f"/api/leads/{booked['id']}", json={"stage": "booked"}, headers=op)
    assert resp.json()["stage"] == "booked"
    [done] = await tasks_of(TaskType.NEW_LEAD, TaskStatus.DONE)
    assert str(done.lead_id) == booked["id"] and done.outcome == Outcome.BOOKED
    assert [(p["old"], p["new"]) for p in changes] == [("new", "lost"), ("new", "booked")]


async def test_refused_inquiry_closes_its_other_calls(client: AsyncClient, op: dict) -> None:
    lead = (await client.post("/api/leads", json={"phone": "900003333"}, headers=op)).json()
    await call_event(
        pbx_id="3.1", status=CallStatus.MISSED, phone="+998900003333", lead_id=uuid.UUID(lead["id"])
    )
    [new_lead] = await tasks_of(TaskType.NEW_LEAD)
    await client.post(
        f"/api/tasks/{new_lead.id}/result",
        json={"outcome": "refused", "reason": "far"},
        headers=op,
    )
    assert await tasks_of(TaskType.MISSED_CALL) == []
    stored = (await client.get("/api/leads", headers=op)).json()["items"][0]
    assert stored["stage"] == "lost" and stored["lost_reason"] == "far"


# --- generators -------------------------------------------------------------------------------


async def test_no_course_or_repeat_call_when_already_booked(
    client: AsyncClient, clinic: dict, op: dict, sup: dict
) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(Service)
            .where(Service.id == uuid.UUID(clinic["laser"]))
            .values(course_sessions=4)
        )
        await s.commit()
    monday = next_monday()
    laser = {"doctor": "d2", "service": "laser"}
    first = (
        await client.post(
            "/api/appointments", json=booking(clinic, at(monday, 9), **laser), headers=op
        )
    ).json()
    nxt = await client.post(
        "/api/appointments", json=booking(clinic, at(monday + timedelta(days=7), 9), **laser),
        headers=op,
    )  # fmt: skip
    assert nxt.status_code == 201, nxt.text
    for st in ("arrived", "completed"):
        await client.post(
            f"/api/appointments/{first['id']}/status", json={"status": st}, headers=op
        )
    assert await tasks_of(TaskType.COURSE_CONTINUE) == []  # the next session is booked

    due = (monday + timedelta(days=30)).isoformat()
    rec = {"patient_id": clinic["patient"], "due_date": due}
    assert (await client.post("/api/recommendations", json=rec, headers=sup)).status_code == 201
    assert await tasks_of(TaskType.REPEAT_VISIT) == []  # already has a visit ahead

    # without a booking ahead both calls are created
    await client.post(
        f"/api/appointments/{nxt.json()['id']}/status",
        json={"status": "cancelled", "reason": "price"},
        headers=op,
    )
    third = (
        await client.post(
            "/api/appointments",
            json=booking(clinic, at(monday + timedelta(days=14), 9), **laser),
            headers=op,
        )  # fmt: skip
    ).json()
    for st in ("arrived", "completed"):
        await client.post(
            f"/api/appointments/{third['id']}/status", json={"status": st}, headers=op
        )
    assert len(await tasks_of(TaskType.COURSE_CONTINUE)) == 1
    assert (await client.post("/api/recommendations", json=rec, headers=sup)).status_code == 201
    assert len(await tasks_of(TaskType.REPEAT_VISIT)) == 1


# --- campaigns --------------------------------------------------------------------------------


async def _cold_patients(n: int) -> None:
    async with SessionLocal() as s:
        for i in range(n):
            s.add(
                Patient(
                    full_name=f"Kamp {i}", search_key=f"kamp {i}", kind=PatientKind.COLD, tags=[],
                    district="Oltiariq",
                    phones=[PatientPhone(number=f"+9989000030{i:02d}", is_primary=True)],
                )
            )  # fmt: skip
        await s.commit()


async def test_campaign_scripts_and_status_rules(client: AsyncClient, sup: dict) -> None:
    await _cold_patients(6)
    base = {"name": "Oltiariq", "segment": {"districts": ["Oltiariq"]}, "daily_limit": 2}
    same = await client.post(
        "/api/campaigns", json={**base, "script_code_b": "reactivation"}, headers=sup
    )
    assert same.status_code == 400 and same.json()["detail"] == "same_script"
    created = (await client.post("/api/campaigns", json=base, headers=sup)).json()
    assert created["script_code"] == "reactivation"  # the default is stored explicitly
    url = f"/api/campaigns/{created['id']}/status"

    paused = await client.post(url, json={"status": "paused"}, headers=sup)
    assert paused.status_code == 400 and paused.json()["detail"] == "invalid_transition"
    await client.post(url, json={"status": "active"}, headers=sup)
    assert len(await tasks_of(TaskType.CAMPAIGN)) == 2

    # pausing takes the calls out of the queue; resuming brings the day's calls back
    await client.post(url, json={"status": "paused"}, headers=sup)
    assert await tasks_of(TaskType.CAMPAIGN) == []
    resumed = (await client.post(url, json={"status": "active"}, headers=sup)).json()
    assert resumed["status"] == "active" and len(await tasks_of(TaskType.CAMPAIGN)) == 2

    await client.post(url, json={"status": "finished"}, headers=sup)
    assert await tasks_of(TaskType.CAMPAIGN) == []
    again = await client.post(url, json={"status": "active"}, headers=sup)
    assert again.status_code == 400  # finished is final


async def test_campaign_past_its_end_date_generates_nothing(client: AsyncClient, sup: dict) -> None:
    await _cold_patients(3)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    body = {"name": "Eski", "segment": {"districts": ["Oltiariq"]}, "ends_on": yesterday}
    created = (await client.post("/api/campaigns", json=body, headers=sup)).json()
    resp = await client.post(
        f"/api/campaigns/{created['id']}/status", json={"status": "active"}, headers=sup
    )
    assert resp.status_code == 400 and resp.json()["detail"] == "campaign_ended"

    async with SessionLocal() as s:
        campaign = await s.get(Campaign, uuid.UUID(created["id"]))
        campaign.status = CampaignStatus.ACTIVE
        assert await campaigns.generate_for_campaign(s, campaign) == 0
        assert await campaigns.generate_all(s) == 0
        assert campaign.status is CampaignStatus.FINISHED
        await s.commit()
    assert await tasks_of(TaskType.CAMPAIGN) == []


# --- reports ----------------------------------------------------------------------------------


async def test_booking_closing_a_task_is_not_a_dial_attempt(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    async with SessionLocal() as s:
        await tasks.create_task(
            s,
            TaskType.REACTIVATION,
            due_at=clinic_time.now(),
            patient_id=uuid.UUID(clinic["patient"]),
        )
        await s.commit()
    appt = (
        await client.post(
            "/api/appointments", json=booking(clinic, at(next_monday(), 9)), headers=op
        )
    ).json()
    async with SessionLocal() as s:
        [attempt] = list(await s.scalars(select(TaskAttempt)))
    assert attempt.outcome == Outcome.BOOKED and attempt.automatic

    daily = (await client.get("/api/reports/daily", headers=op)).json()
    assert daily["outbound_attempts"] == 0 and daily["dial_rate"] is None
    assert daily["campaign_outcomes"] == {"booked": 1}  # still a booking from the base

    await make_user("owner1", Role.OWNER)
    owner = bearer(await login(client, "owner1"))
    await client.post(
        f"/api/appointments/{appt['id']}/status", json={"status": "arrived"}, headers=op
    )
    params = {"from": clinic_time.today().isoformat(), "to": next_monday().isoformat()}
    kpi = (await client.get("/api/reports/kpi", params=params, headers=owner)).json()
    assert kpi["attempts"] == 0 and kpi["dial_rate"] is None and kpi["operators"] == []
    # the reactivated patient came: TZ 4.11 "returned patients"
    assert kpi["returned_patients"] == 1


async def test_confirmation_rate_is_confirmed_over_the_days_appointments(
    client: AsyncClient, clinic: dict
) -> None:
    today = clinic_time.today()
    async with SessionLocal() as s:
        rows = []
        for hour, status in (
            (8, S.CONFIRMED),
            (9, S.SCHEDULED),
            (10, S.NO_SHOW),
            (11, S.RESCHEDULED),
        ):
            starts = clinic_time.at(today, time(hour))
            appt = Appointment(
                patient_id=uuid.UUID(clinic["patient"]), branch_id=uuid.UUID(clinic["branch"]),
                doctor_id=uuid.UUID(clinic["d1"]), starts_at=starts,
                ends_at=starts + timedelta(minutes=30), status=status,
            )  # fmt: skip
            s.add(appt)
            rows.append(appt)
        await s.flush()
        # the no-show had confirmed on the phone that morning
        await tasks.create_task(
            s, TaskType.CONFIRM_VISIT, due_at=clinic_time.now(), patient_id=rows[2].patient_id,
            appointment_id=rows[2].id, dedupe_key=f"confirm:{rows[2].id}",
        )  # fmt: skip
        await s.execute(
            update(Task).where(Task.appointment_id == rows[2].id).values(outcome=Outcome.CONFIRMED)
        )
        await s.commit()
    await make_user("owner1", Role.OWNER)
    owner = bearer(await login(client, "owner1"))
    params = {"from": today.isoformat(), "to": today.isoformat()}
    kpi = (await client.get("/api/reports/kpi", params=params, headers=owner)).json()
    assert kpi["confirmation_rate"] == 66.7  # 2 confirmed of 3 (the rescheduled one moved away)


async def test_report_operators_list(client: AsyncClient, op: dict, sup: dict) -> None:
    await make_user("op_old", Role.OPERATOR, active=False)
    await make_user("reg1", Role.REGISTRAR)
    names = [
        o["full_name"] for o in (await client.get("/api/reports/operators", headers=sup)).json()
    ]
    assert names == ["Op1", "Sup1"]
    assert (await client.get("/api/reports/operators", headers=op)).status_code == 403


async def test_out_of_range_dates_are_client_errors(
    client: AsyncClient, op: dict, sup: dict
) -> None:
    far = {"from": "9999-12-31", "to": "9999-12-31"}
    for path in ("/api/reports/kpi", "/api/reports/kpi.xlsx"):
        assert (await client.get(path, params=far, headers=sup)).status_code == 400
        swapped = {"from": "2026-02-01", "to": "2026-01-01"}
        assert (await client.get(path, params=swapped, headers=sup)).status_code == 400
    daily = await client.get("/api/reports/daily", params={"date": "9999-12-31"}, headers=op)
    assert daily.status_code == 400
    assert (
        await client.get("/api/ai/qa/overview", params={"to": "9999-12-31"}, headers=sup)
    ).status_code == 400
    assert (
        await client.get("/api/ai/qa/calls", params={"limit": 0}, headers=sup)
    ).status_code == 422
    assert (
        await client.get("/api/leads", params={"since": "9999-12-31"}, headers=op)
    ).status_code == 400


# --- site webhook -----------------------------------------------------------------------------


async def test_site_webhook_bad_body_and_duplicates(client: AsyncClient) -> None:
    settings = get_settings()
    settings.site_webhook_secret = "test-secret"
    try:

        def signed(payload: bytes) -> dict[str, str]:
            sig = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
            return {"X-Signature": f"sha256={sig}"}

        url = "/api/integrations/site/appointments"
        for bad in (b"not json", json.dumps({"id": "x1"}).encode()):
            resp = await client.post(url, content=bad, headers=signed(bad))
            assert resp.status_code == 422
        payload = json.dumps({"id": "dup1", "phone_number": "+998 90 000 44 55"}).encode()
        responses = await asyncio.gather(
            *(client.post(url, content=payload, headers=signed(payload)) for _ in range(3))
        )
        assert [r.status_code for r in responses] == [202, 202, 202]
        assert sorted(r.json()["status"] for r in responses) == [
            "created",
            "duplicate",
            "duplicate",
        ]
        async with SessionLocal() as s:
            assert await s.scalar(select(func.count()).select_from(Lead)) == 1
    finally:
        settings.site_webhook_secret = ""
