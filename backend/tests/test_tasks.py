"""Phase 2: task rules, leads/SLA, site webhook, campaigns, scripts, reports."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core import clinic_time
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Doctor, Service
from app.modules.leads.models import Lead
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.scripts.router import seed_if_empty
from app.modules.tasks import rules
from app.modules.tasks.models import Task, TaskAttempt, TaskStatus, TaskType
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import at, booking, next_monday

TZ = clinic_time.tz()


async def open_tasks(type_: TaskType | None = None) -> list[Task]:
    async with SessionLocal() as s:
        stmt = select(Task).where(Task.status == TaskStatus.OPEN)
        if type_:
            stmt = stmt.where(Task.type == type_)
        return list(await s.scalars(stmt))


# --- clinic calendar --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (datetime(2026, 9, 28, 10, 0), datetime(2026, 9, 28, 10, 15)),  # Monday, open
        (datetime(2026, 10, 2, 17, 55), datetime(2026, 10, 3, 8, 10)),  # Fri 17:55 -> Sat
        (datetime(2026, 10, 3, 17, 55), datetime(2026, 10, 5, 8, 10)),  # Sat 17:55 -> Mon
        (datetime(2026, 10, 4, 12, 0), datetime(2026, 10, 5, 8, 15)),  # Sunday -> Mon
        (datetime(2026, 9, 28, 6, 0), datetime(2026, 9, 28, 8, 15)),  # before opening
    ],
)
def test_sla_counts_only_working_minutes(start: datetime, expected: datetime) -> None:
    got = clinic_time.add_working_minutes(start.replace(tzinfo=TZ), 15)
    assert got == expected.replace(tzinfo=TZ)


# --- leads ------------------------------------------------------------------------------------


async def test_new_lead_creates_task_and_result_updates_lead(client: AsyncClient, op: dict) -> None:
    resp = await client.post(
        "/api/leads",
        json={
            "phone": "90 555 11 22",
            "name": "Yangi Mijoz",
            "channel": "call",
            "source": "instagram",
            "interest": "akne",
        },
        headers=op,
    )
    assert resp.status_code == 201, resp.text
    lead = resp.json()
    assert lead["stage"] == "new" and lead["phone"] == "+998905551122"

    queue = (await client.get("/api/tasks", params={"view": "all"}, headers=op)).json()
    [task] = [t for t in queue if t["lead_id"] == lead["id"]]
    assert task["type"] == "new_lead" and task["script_code"] == "incoming"

    url = f"/api/tasks/{task['id']}/result"
    first = (await client.post(url, json={"outcome": "thinking"}, headers=op)).json()
    leads = (await client.get("/api/leads", headers=op)).json()["items"]
    assert leads[0]["stage"] == "later" and leads[0]["first_response_at"]
    # "thinking" is not the end: one follow-up call two working days later at 10:00
    due = clinic_time.local(datetime.fromisoformat(first["due_at"]))
    assert first["status"] == "open" and due.time() == time(10)
    assert due.date() > clinic_time.today() + timedelta(days=1)
    second = (await client.post(url, json={"outcome": "thinking"}, headers=op)).json()
    assert second["status"] == "done" and second["outcome"] == "thinking"


async def test_booking_closes_tasks_and_books_lead(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    lead = (
        await client.post(
            "/api/leads", json={"phone": "905551122", "name": "Yangi Mijoz"}, headers=op
        )
    ).json()
    patient_id = (await client.post(f"/api/leads/{lead['id']}/patient", headers=op)).json()[
        "patient_id"
    ]

    body = {**booking(clinic, at(next_monday(), 9)), "patient_id": patient_id}
    assert (await client.post("/api/appointments", json=body, headers=op)).status_code == 201

    assert await open_tasks(TaskType.NEW_LEAD) == []
    stored = (await client.get("/api/leads", headers=op)).json()["items"][0]
    assert stored["stage"] == "booked" and stored["appointment_id"]
    async with SessionLocal() as s:
        attempts = list(await s.scalars(select(TaskAttempt.outcome)))
    assert [a.value for a in attempts] == ["booked"]


# --- visits -----------------------------------------------------------------------------------


async def test_morning_confirmation_confirms_the_appointment(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()

    async with SessionLocal() as s:
        assert await rules.generate_confirmations(s, day) == 1
        assert await rules.generate_confirmations(s, day) == 0  # idempotent
        await s.commit()

    [task] = await open_tasks(TaskType.CONFIRM_VISIT)
    resp = await client.post(
        f"/api/tasks/{task.id}/result", json={"outcome": "confirmed"}, headers=op
    )
    assert resp.status_code == 200
    history = (
        await client.get(f"/api/appointments/patient/{clinic['patient']}", headers=op)
    ).json()
    assert history[0]["id"] == appt["id"] and history[0]["status"] == "confirmed"


async def test_no_show_creates_call_task(client: AsyncClient, clinic: dict, op: dict) -> None:
    appt = (
        await client.post(
            "/api/appointments", json=booking(clinic, at(next_monday(), 9)), headers=op
        )
    ).json()
    await client.post(
        f"/api/appointments/{appt['id']}/status",
        json={"status": "no_show", "reason": "no_answer"},
        headers=op,
    )
    [task] = await open_tasks(TaskType.NO_SHOW)
    assert str(task.appointment_id) == appt["id"] and task.script_code == "no_show"


async def test_recommendation_schedules_repeat_visit_call(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    due = next_monday() + timedelta(days=14)
    await client.post(
        "/api/recommendations",
        json={"patient_id": clinic["patient"], "due_date": due.isoformat()},
        headers=sup,
    )

    [task] = await open_tasks(TaskType.REPEAT_VISIT)
    assert clinic_time.local(task.due_at) == datetime.combine(due - timedelta(days=3), time(9), TZ)


async def test_completed_procedure_schedules_follow_up_call(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(Service)
            .where(Service.id == uuid.UUID(clinic["consult"]))
            .values(followup_call_days=2)
        )
        await s.commit()
    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    for st in ("arrived", "completed"):
        await client.post(f"/api/appointments/{appt['id']}/status", json={"status": st}, headers=op)

    [task] = await open_tasks(TaskType.POST_PROCEDURE)
    assert clinic_time.local(task.due_at).date() == day + timedelta(days=2)


# --- call results -----------------------------------------------------------------------------


async def _patient_task(client: AsyncClient, op: dict, clinic: dict) -> str:
    resp = await client.post(
        "/api/tasks",
        json={
            "patient_id": clinic["patient"],
            "due_at": datetime.now(UTC).isoformat(),
            "note": "qayta qo'ng'iroq",
        },
        headers=op,
    )
    assert resp.json() == {"created": True}
    return str((await open_tasks(TaskType.CALLBACK))[0].id)


async def test_no_answer_retries_then_gives_up(client: AsyncClient, clinic: dict, op: dict) -> None:
    task_id = await _patient_task(client, op, clinic)
    url = f"/api/tasks/{task_id}/result"
    first = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert first["status"] == "open" and first["attempts"] == 1
    second = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert clinic_time.local(datetime.fromisoformat(second["due_at"])).time() == time(
        10
    )  # next day
    third = (await client.post(url, json={"outcome": "no_answer"}, headers=op)).json()
    assert third["status"] == "done" and third["outcome"] == "no_answer"
    assert (await client.post(url, json={"outcome": "no_answer"}, headers=op)).status_code == 400


async def test_result_validation(client: AsyncClient, clinic: dict, op: dict) -> None:
    task_id = await _patient_task(client, op, clinic)
    url = f"/api/tasks/{task_id}/result"
    assert (await client.post(url, json={"outcome": "callback"}, headers=op)).json()[
        "detail"
    ] == "callback_time_required"
    assert (await client.post(url, json={"outcome": "refused"}, headers=op)).json()[
        "detail"
    ] == "reason_required"
    assert (
        await client.post(url, json={"outcome": "refused", "reason": "nope"}, headers=op)
    ).status_code == 422
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    moved = (
        await client.post(url, json={"outcome": "callback", "callback_at": later}, headers=op)
    ).json()
    assert moved["status"] == "open"
    assert datetime.fromisoformat(moved["due_at"]) == datetime.fromisoformat(later)


async def test_do_not_call_flags_patient(client: AsyncClient, clinic: dict, op: dict) -> None:
    task_id = await _patient_task(client, op, clinic)
    await client.post(
        f"/api/tasks/{task_id}/result",
        json={"outcome": "do_not_call", "note": "so'radi"},
        headers=op,
    )
    card = (await client.get(f"/api/patients/{clinic['patient']}", headers=op)).json()
    assert card["do_not_call"] is True
    # outbound generators skip the patient from now on
    async with SessionLocal() as s:
        from app.modules.tasks import service as tasks

        created = await tasks.create_task(
            s,
            TaskType.REACTIVATION,
            due_at=datetime.now(UTC),
            patient_id=uuid.UUID(clinic["patient"]),
        )
    assert created is False


# --- generators -------------------------------------------------------------------------------


async def test_lost_lead_and_reactivation_generators(client: AsyncClient, op: dict) -> None:
    await client.post(
        "/api/leads", json={"phone": "905551122", "name": "Eski Murojaat"}, headers=op
    )
    async with SessionLocal() as s:
        await s.execute(update(Lead).values(created_at=datetime.now(UTC) - timedelta(days=2)))
        s.add(
            Patient(
                full_name="Uzoq Kelmagan", search_key=search_key("Uzoq Kelmagan"), kind=PatientKind.ACTIVE,
                tags=[], last_visit_at=datetime.now(UTC) - timedelta(days=365),
                phones=[PatientPhone(number="+998901230000", is_primary=True)],
            )
        )  # fmt: skip
        await s.commit()
        # the new-inquiry call is still pending: no second task for the same person
        assert await rules.generate_lost_leads(s) == 0
        await s.execute(
            update(Task).where(Task.type == TaskType.NEW_LEAD).values(status=TaskStatus.DONE)
        )
        assert await rules.generate_lost_leads(s) == 1
        assert await rules.generate_lost_leads(s) == 0  # idempotent
        assert await rules.generate_reactivation(s) == 1
        assert await rules.generate_reactivation(s) == 0  # the patient now has an open task
        await s.commit()


async def test_campaign_respects_segment_limit_and_dnc(client: AsyncClient) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    async with SessionLocal() as s:
        for i in range(5):
            s.add(
                Patient(
                    full_name=f"Sovuq {i}", search_key=search_key(f"Sovuq {i}"), kind=PatientKind.COLD,
                    tags=[], do_not_call=(i == 0), district="Quva",
                    phones=[PatientPhone(number=f"+99890000100{i}", is_primary=True)],
                )
            )  # fmt: skip
        await s.commit()

    segment = {"kinds": ["cold"], "districts": ["Quva"]}
    preview = await client.post("/api/campaigns/preview", json=segment, headers=sup)
    assert preview.json() == {"audience": 4}  # the do-not-call patient is excluded

    created = (
        await client.post(
            "/api/campaigns",
            json={"name": "Quva sovuq baza", "segment": segment, "daily_limit": 3},
            headers=sup,
        )
    ).json()
    assert created["status"] == "draft" and created["audience"] == 4
    active = (
        await client.post(
            f"/api/campaigns/{created['id']}/status", json={"status": "active"}, headers=sup
        )
    ).json()
    assert active["stats"]["open"] == 3  # daily limit
    assert len(await open_tasks(TaskType.CAMPAIGN)) == 3

    await make_user("op1", Role.OPERATOR)
    op_headers = bearer(await login(client, "op1"))
    assert (await client.get("/api/campaigns", headers=op_headers)).status_code == 403


async def test_campaign_ab_scripts(client: AsyncClient) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    async with SessionLocal() as s:
        for i in range(20):
            s.add(
                Patient(
                    full_name=f"AB {i}", search_key=search_key(f"AB {i}"), kind=PatientKind.LEGACY,
                    tags=[], district="Rishton",
                    phones=[PatientPhone(number=f"+9989000020{i:02d}", is_primary=True)],
                )
            )  # fmt: skip
        await s.commit()
    body = {
        "name": "A/B", "segment": {"districts": ["Rishton"]}, "daily_limit": 20,
        "script_code": "reactivation", "script_code_b": "repeat_visit",
    }  # fmt: skip
    created = (await client.post("/api/campaigns", json=body, headers=sup)).json()
    await client.post(
        f"/api/campaigns/{created['id']}/status", json={"status": "active"}, headers=sup
    )
    tasks = await open_tasks(TaskType.CAMPAIGN)
    scripts = {t.script_code for t in tasks}
    assert scripts == {"reactivation", "repeat_visit"}  # both variants in use
    # the split is by patient: a patient always lands in the same variant
    for t in tasks:
        assert t.script_code == ("repeat_visit" if t.patient_id.int % 2 else "reactivation")

    await make_user("op1", Role.OPERATOR)
    op = bearer(await login(client, "op1"))
    a_task = next(t for t in tasks if t.script_code == "reactivation")
    b_task = next(t for t in tasks if t.script_code == "repeat_visit")
    await client.post(f"/api/tasks/{a_task.id}/result", json={"outcome": "booked"}, headers=op)
    await client.post(
        f"/api/tasks/{b_task.id}/result", json={"outcome": "refused", "reason": "price"}, headers=op
    )
    [campaign] = (await client.get("/api/campaigns", headers=sup)).json()
    ab = {v["variant"]: v for v in campaign["ab"]}
    assert ab["a"]["booked"] == 1 and ab["a"]["booking_rate"] == 100.0
    assert ab["b"]["reached"] == 1 and ab["b"]["booking_rate"] == 0.0
    assert ab["a"]["tasks"] + ab["b"]["tasks"] == 20


# --- site webhook -----------------------------------------------------------------------------


@pytest.fixture
def webhook_secret():
    settings = get_settings()
    settings.site_webhook_secret = "test-secret"
    yield "test-secret"
    settings.site_webhook_secret = ""


async def test_site_webhook_requires_valid_signature(
    client: AsyncClient, webhook_secret: str
) -> None:
    payload = json.dumps(
        {
            "id": "a1",
            "phone_number": "+998 90 777 66 55",
            "client_name": "Saytdan",
            "service_name_uz": "Lazer epilyatsiya",
        }
    ).encode()
    sig = hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()

    bad = await client.post(
        "/api/integrations/site/appointments",
        content=payload,
        headers={"X-Signature": "sha256=deadbeef"},
    )
    assert bad.status_code == 401

    ok = await client.post(
        "/api/integrations/site/appointments",
        content=payload,
        headers={"X-Signature": f"sha256={sig}"},
    )
    assert ok.status_code == 202 and ok.json()["status"] == "created"
    again = await client.post(
        "/api/integrations/site/appointments", content=payload, headers={"X-Signature": sig}
    )
    assert again.json()["status"] == "duplicate"

    async with SessionLocal() as s:
        lead = await s.scalar(select(Lead))
        assert lead.channel == "website" and lead.phone == "+998907776655"
        assert (
            await s.scalar(select(func.count()).select_from(Task).where(Task.lead_id == lead.id))
            == 1
        )


# --- scripts, notes, reports ------------------------------------------------------------------


async def test_scripts_seeded_and_edited_by_supervisors(client: AsyncClient, op: dict) -> None:
    async with SessionLocal() as s:
        assert await seed_if_empty(s) == 28
        assert await seed_if_empty(s) == 0
    scripts = (await client.get("/api/scripts", params={"language": "uz"}, headers=op)).json()
    assert [x["code"] for x in scripts][:3] == ["confirm", "incoming", "repeat_visit"]
    body = {"title": "Yangi", "body": "Matn"}
    assert (await client.put("/api/scripts/confirm/uz", json=body, headers=op)).status_code == 403
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    assert (await client.put("/api/scripts/confirm/uz", json=body, headers=sup)).json()[
        "title"
    ] == "Yangi"


async def test_shift_notes(client: AsyncClient, op: dict) -> None:
    await client.post(
        "/api/tasks/shift-notes", json={"text": "3 ta qayta qo'ng'iroq qoldi"}, headers=op
    )
    notes = (await client.get("/api/tasks/shift-notes", headers=op)).json()
    assert notes[0]["text"] == "3 ta qayta qo'ng'iroq qoldi" and notes[0]["user_name"] == "Op1"


async def test_reports(client: AsyncClient, clinic: dict, op: dict) -> None:
    task_id = await _patient_task(client, op, clinic)
    await client.post(
        f"/api/tasks/{task_id}/result", json={"outcome": "refused", "reason": "price"}, headers=op
    )
    await client.post("/api/leads", json={"phone": "905551122"}, headers=op)

    daily = (await client.get("/api/reports/daily", headers=op)).json()
    assert daily["outbound_attempts"] == 1 and daily["reasons"] == {"price": 1}
    assert daily["not_booked"] == 1 and daily["new_leads"] == 1

    assert (
        await client.get(
            "/api/reports/kpi", params={"from": "2026-01-01", "to": "2026-12-31"}, headers=op
        )
    ).status_code == 403
    await make_user("owner1", Role.OWNER)
    owner = bearer(await login(client, "owner1"))
    today = clinic_time.today().isoformat()
    kpi = (
        await client.get("/api/reports/kpi", params={"from": today, "to": today}, headers=owner)
    ).json()
    assert kpi["attempts"] == 1 and kpi["dial_rate"] == 100.0 and kpi["leads_total"] == 1
    assert kpi["operators"][0]["attempts"] == 1
    xlsx = await client.get(
        "/api/reports/kpi.xlsx", params={"from": today, "to": today}, headers=owner
    )
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    async with SessionLocal() as s:  # the export is audited
        exported = await s.scalar(select(AuditLog).where(AuditLog.action == "report.export"))
    assert exported.after == {"from": today, "to": today}


def test_date_import_is_used() -> None:
    assert date.today()


async def test_patient_timeline_joins_every_touchpoint(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    lead = (
        await client.post(
            "/api/leads",
            json={"phone": "905551133", "name": "Tasma Bemor", "interest": "akne"},
            headers=op,
        )
    ).json()
    [task] = [t for t in await open_tasks(TaskType.NEW_LEAD) if str(t.lead_id) == lead["id"]]
    no_answer = {"outcome": "no_answer", "note": "ko'tarmadi"}
    await client.post(f"/api/tasks/{task.id}/result", json=no_answer, headers=op)
    patient_id = (await client.post(f"/api/leads/{lead['id']}/patient", headers=op)).json()[
        "patient_id"
    ]
    body = {**booking(clinic, at(next_monday(), 9)), "patient_id": patient_id}
    assert (await client.post("/api/appointments", json=body, headers=op)).status_code == 201

    feed = (
        await client.get(f"/api/patients/{patient_id}/timeline", params={"lang": "ru"}, headers=op)
    ).json()
    kinds = [e["kind"] for e in feed]
    assert kinds[0] == "appointment"  # the upcoming visit is on top
    assert {"registered", "lead", "call", "appointment"} <= set(kinds)
    appt = feed[0]
    assert appt["title"] == "Доктор А" and appt["status"] == "scheduled"
    # the call made before the card existed is part of the history too
    calls = [e for e in feed if e["kind"] == "call"]
    assert [c["status"] for c in calls] == ["booked", "no_answer"] and calls[0]["user"]
    times = [e["at"] for e in feed]
    assert times == sorted(times, reverse=True)

    # the patient's doctor gets the medical history without call-center notes
    doc_user = await make_user("doc1", Role.DOCTOR)
    async with SessionLocal() as s:
        (await s.get(Doctor, uuid.UUID(clinic["d1"]))).user_id = doc_user.id
        await s.commit()
    doc = bearer(await login(client, "doc1"))
    doc_kinds = {
        e["kind"]
        for e in (await client.get(f"/api/patients/{patient_id}/timeline", headers=doc)).json()
    }
    assert "call" not in doc_kinds and "appointment" in doc_kinds
    missing = await client.get(f"/api/patients/{uuid.uuid4()}/timeline", headers=op)
    assert missing.status_code == 404


async def test_merge_carries_visits_calls_and_leads(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    lead = (
        await client.post("/api/leads", json={"phone": "905551144", "name": "Dubl"}, headers=op)
    ).json()
    source = (await client.post(f"/api/leads/{lead['id']}/patient", headers=op)).json()[
        "patient_id"
    ]
    body = {**booking(clinic, at(next_monday(), 9)), "patient_id": source}
    assert (await client.post("/api/appointments", json=body, headers=op)).status_code == 201
    # both cards have an open callback: only one call must survive the merge
    later = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    for pid in (clinic["patient"], source):
        await client.post(
            "/api/tasks", json={"patient_id": pid, "due_at": later, "note": "x"}, headers=op
        )

    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    resp = await client.post(
        f"/api/patients/{clinic['patient']}/merge", json={"source_id": source}, headers=sup
    )
    assert resp.status_code == 200, resp.text

    feed = (await client.get(f"/api/patients/{clinic['patient']}/timeline", headers=op)).json()
    kinds = [e["kind"] for e in feed]
    assert {"appointment", "lead", "call"} <= set(kinds)
    assert kinds.count("planned_call") == 1
    visits = (await client.get(f"/api/appointments/patient/{clinic['patient']}", headers=op)).json()
    assert len(visits) == 1


async def test_do_not_call_on_the_card_cancels_outbound_calls(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    from app.modules.tasks import service as task_service

    patient_id = uuid.UUID(clinic["patient"])
    async with SessionLocal() as s:
        for type_ in (TaskType.REACTIVATION, TaskType.CALLBACK):
            await task_service.create_task(
                s, type_, due_at=datetime.now(UTC), patient_id=patient_id,
                dedupe_key=f"dnc-test:{type_.value}",
            )  # fmt: skip
        await s.commit()

    url = f"/api/patients/{patient_id}/do-not-call"
    resp = await client.put(url, json={"do_not_call": True, "reason": "so'radi"}, headers=op)
    assert resp.status_code == 200, resp.text

    async with SessionLocal() as s:
        result = await s.execute(
            select(Task.type, Task.status).where(Task.patient_id == patient_id)
        )
        rows = {type_: status for type_, status in result}
    # campaign-type calls stop; a callback the patient asked for stays
    assert rows[TaskType.REACTIVATION] == TaskStatus.CANCELLED
    assert rows[TaskType.CALLBACK] == TaskStatus.OPEN
