"""Patient card & list, inquiries (source, funnel, drawer) and the operator queue
(script context, attempts, completed tab, supervisor actions) — TZ 4.1, 4.4, 4.5, 4.6."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core import clinic_time
from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.audit.models import AuditLog
from app.modules.campaigns.models import Campaign
from app.modules.diagnoses import service as diagnoses
from app.modules.diagnoses.models import DiagnosisMapping, MappingMethod, MappingStatus
from app.modules.leads import service as leads_service
from app.modules.leads.models import Lead, LeadChannel
from app.modules.messaging.models import Channel, Conversation, Direction, Message, MessageStatus
from app.modules.patients.models import (
    Patient,
    PatientCondition,
    PatientKind,
    PatientPhone,
    Source,
)
from app.modules.tasks import service as tasks_service
from app.modules.tasks.models import Task, TaskStatus, TaskType
from app.modules.telephony.models import Call, CallDirection, CallStatus
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import at, booking, next_monday


@pytest.fixture
async def sup(client: AsyncClient) -> dict:
    await make_user("sup1", Role.SUPERVISOR)
    return bearer(await login(client, "sup1"))


async def new_lead(client: AsyncClient, headers: dict, **body) -> dict:
    resp = await client.post("/api/leads", json={"source": "instagram", **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- inquiries: the ad source (TZ 4.4) ---------------------------------------------------------


async def test_a_lead_entered_by_staff_needs_its_ad_source(client: AsyncClient, op: dict) -> None:
    missing = await client.post("/api/leads", json={"phone": "901112233"}, headers=op)
    assert missing.status_code == 422 and missing.json()["detail"] == "source_required"

    lead = await new_lead(client, op, phone="901112233", source="google")
    assert lead["source"] == "google"
    url = f"/api/leads/{lead['id']}"
    cleared = await client.patch(url, json={"source": None}, headers=op)
    assert cleared.status_code == 422 and cleared.json()["detail"] == "source_required"
    changed = await client.patch(url, json={"source": "maps", "name": "Aziza"}, headers=op)
    assert changed.json()["source"] == "maps" and changed.json()["name"] == "Aziza"


async def test_leads_that_arrive_by_themselves_get_the_source_of_their_channel() -> None:
    async with SessionLocal() as s:
        known = Patient(
            full_name="Eski Bemor", search_key=search_key("Eski Bemor"), kind=PatientKind.LEGACY,
            tags=[], phones=[PatientPhone(number="+998901110000", is_primary=True)],
        )  # fmt: skip
        s.add(known)
        await s.flush()
        cases = {
            (LeadChannel.TELEGRAM, None): Source.TELEGRAM,
            (LeadChannel.INSTAGRAM, None): Source.INSTAGRAM,
            (LeadChannel.WEBSITE, None): Source.WEBSITE,
            (LeadChannel.MISSED_CALL, "+998907770000"): Source.OTHER,  # nobody we know
            (LeadChannel.MISSED_CALL, "+998901110000"): Source.RETURNING,  # an old patient
        }
        for (channel, phone), expected in cases.items():
            lead, _ = await leads_service.create_lead(s, channel=channel, phone=phone)
            assert lead.source is expected, channel
        # an explicit source wins over the channel default
        lead, _ = await leads_service.create_lead(
            s, channel=LeadChannel.TELEGRAM, phone=None, source=Source.RECOMMENDATION
        )
        assert lead.source is Source.RECOMMENDATION
        await s.rollback()


# --- inquiries: list, funnel, drawer -----------------------------------------------------------


async def test_lead_filters_funnel_and_overdue_rows(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    a = await new_lead(client, op, phone="901000001", name="A", source="instagram")
    b = await new_lead(client, op, phone="901000002", name="B", source="google")
    await new_lead(client, op, phone="901000003", name="C", source="instagram")
    await client.patch(f"/api/leads/{b['id']}", json={"stage": "contacted"}, headers=op)
    # A books and confirms: it passes every step up to "confirmed"
    pid = (await client.post(f"/api/leads/{a['id']}/patient", headers=op)).json()["patient_id"]
    appt = (
        await client.post(
            "/api/appointments",
            json={**booking(clinic, at(next_monday(), 9)), "patient_id": pid},
            headers=op,
        )
    ).json()
    await client.post(
        f"/api/appointments/{appt['id']}/status", json={"status": "confirmed"}, headers=op
    )

    page = (await client.get("/api/leads", headers=op)).json()
    assert page["funnel"] == {"new": 3, "contacted": 2, "booked": 1, "confirmed": 1, "visited": 0}
    assert page["by_stage"] == {"new": 1, "contacted": 1, "confirmed": 1}

    insta = (await client.get("/api/leads", params={"source": "instagram"}, headers=op)).json()
    assert insta["total"] == 2 and insta["funnel"]["new"] == 2
    # the stage filter narrows the rows, not the funnel it is shown against
    only_new = (
        await client.get("/api/leads", params={"source": "instagram", "stage": "new"}, headers=op)
    ).json()
    assert only_new["total"] == 1 and only_new["funnel"]["new"] == 2

    tomorrow = (clinic_time.today() + timedelta(days=1)).isoformat()
    future = (await client.get("/api/leads", params={"since": tomorrow}, headers=op)).json()
    assert future["total"] == 0
    today = clinic_time.today().isoformat()
    until_today = (await client.get("/api/leads", params={"until": today}, headers=op)).json()
    assert until_today["total"] == 3

    # C was never answered and its 15 minutes are up: a red row
    async with SessionLocal() as s:
        await s.execute(
            update(Lead)
            .where(Lead.name == "C")
            .values(sla_due_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await s.commit()
    overdue = (await client.get("/api/leads", params={"sla": "overdue"}, headers=op)).json()
    assert [x["name"] for x in overdue["items"]] == ["C"]
    assert overdue["items"][0]["sla_state"] == "overdue"
    states = {x["name"]: x["sla_state"] for x in page["items"]}
    assert states["A"] == "met" and states["B"] == "met"


async def test_booked_lead_follows_its_visit_to_confirmed_and_visited(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    lead = await new_lead(client, op, phone="902000001", name="Kelgan")
    pid = (await client.post(f"/api/leads/{lead['id']}/patient", headers=op)).json()["patient_id"]
    appt = (
        await client.post(
            "/api/appointments",
            json={**booking(clinic, at(next_monday(), 10)), "patient_id": pid},
            headers=op,
        )
    ).json()
    url = f"/api/appointments/{appt['id']}/status"
    stage = lambda: client.get(f"/api/leads/{lead['id']}", headers=op)  # noqa: E731
    assert (await stage()).json()["stage"] == "booked"
    await client.post(url, json={"status": "confirmed"}, headers=op)
    assert (await stage()).json()["stage"] == "confirmed"
    await client.post(url, json={"status": "arrived"}, headers=op)
    detail = (await stage()).json()
    assert detail["stage"] == "visited"
    assert [(h["old_stage"], h["new_stage"]) for h in detail["history"]] == [
        (None, "new"), ("new", "contacted"), ("contacted", "booked"),
        ("booked", "confirmed"), ("confirmed", "visited"),
    ]  # fmt: skip


async def test_lead_drawer_has_history_tasks_calls_and_messages(
    client: AsyncClient, op: dict
) -> None:
    lead = await new_lead(client, op, phone="903000001", name="Chat Mijoz", interest="akne")
    url = f"/api/leads/{lead['id']}"
    [task] = [t for t in await _open(TaskType.NEW_LEAD) if str(t.lead_id) == lead["id"]]
    await client.post(
        f"/api/tasks/{task.id}/result", json={"outcome": "no_answer", "note": "ko'tarmadi"},
        headers=op,
    )  # fmt: skip
    await client.patch(url, json={"stage": "later"}, headers=op)
    await client.patch(url, json={"stage": "lost", "lost_reason": "price"}, headers=op)
    async with SessionLocal() as s:
        conv = Conversation(
            channel=Channel.TELEGRAM, external_id="tg-1", lead_id=uuid.UUID(lead["id"])
        )
        s.add(conv)
        await s.flush()
        s.add(
            Message(
                conversation_id=conv.id, direction=Direction.IN, text="Narxi qancha?",
                status=MessageStatus.RECEIVED, created_at=clinic_time.now(),
            )
        )  # fmt: skip
        s.add(
            Call(
                pbx_id="drawer-1", direction=CallDirection.OUT, status=CallStatus.NO_ANSWER,
                phone="+998903000001", started_at=clinic_time.now(),
            )
        )  # fmt: skip
        await s.commit()

    detail = (await client.get(url, headers=op)).json()
    assert [(h["new_stage"], h["reason"]) for h in detail["history"]] == [
        ("new", None), ("contacted", None), ("later", None), ("lost", "price"),
    ]  # fmt: skip
    assert detail["history"][-1]["user_name"] == "Op1"
    [t] = detail["tasks"]
    assert t["type"] == "new_lead" and t["status"] == "cancelled"
    assert [(x["outcome"], x["note"], x["user_name"]) for x in t["attempts"]] == [
        ("no_answer", "ko'tarmadi", "Op1")
    ]
    assert [c["status"] for c in detail["calls"]] == ["no_answer"]
    assert [m["text"] for m in detail["messages"]] == ["Narxi qancha?"]
    missing = await client.get(f"/api/leads/{uuid.uuid4()}", headers=op)
    assert missing.status_code == 404


# --- patients list (TZ 4.1) --------------------------------------------------------------------


async def _patients() -> dict[str, uuid.UUID]:
    now = clinic_time.now()
    rows = {
        "Aliyeva Dilnoza": dict(
            kind=PatientKind.ACTIVE, district="Quva", source=Source.INSTAGRAM,
            tags=["vip"], birth_date=date(1990, 5, 1), last_visit_at=now - timedelta(days=30),
            phones=["+998904000001"],
        ),
        "Bobur Karimov": dict(
            kind=PatientKind.LEGACY, district=None, source=Source.IMPORT,
            tags=["tekshirish-kerak"], birth_date=None, last_visit_at=now - timedelta(days=400),
            phones=[],
        ),
        "Vali Soliyev": dict(
            kind=PatientKind.ACTIVE, district="Quva", source=Source.GOOGLE, tags=[],
            birth_date=date(1970, 1, 1), last_visit_at=None, phones=["+998904000003"],
        ),
        "Sovuq Raqam": dict(
            kind=PatientKind.COLD, district=None, source=Source.COLD_BASE, tags=[],
            birth_date=None, last_visit_at=None, phones=["+998904000004"],
        ),
    }  # fmt: skip
    ids = {}
    async with SessionLocal() as s:
        for name, r in rows.items():
            phones = [PatientPhone(number=n, is_primary=True) for n in r.pop("phones")]
            p = Patient(full_name=name, search_key=search_key(name), phones=phones, **r)
            s.add(p)
            await s.flush()
            ids[name] = p.id
        s.add(
            PatientCondition(
                patient_id=ids["Bobur Karimov"], raw_text="алопеция", text_key="alopetsiya",
                category_code="alopecia_androgenic", source="import:main",
            )
        )  # fmt: skip
        s.add(
            DiagnosisMapping(
                text="alopetsiya", category_code="alopecia_androgenic",
                method=MappingMethod.RULE, status=MappingStatus.APPROVED,
            )
        )  # fmt: skip
        await s.commit()
    return ids


async def test_patient_list_filters_and_columns(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    ids = await _patients()
    get = lambda **p: client.get("/api/patients", params=p, headers=op)  # noqa: E731

    def names(resp) -> list[str]:
        return [x["full_name"] for x in resp.json()["items"]]

    assert "Sovuq Raqam" not in names(await get())  # the cold base only on request
    assert names(await get(district="Quva")) == ["Aliyeva Dilnoza", "Vali Soliyev"]
    assert names(await get(district="-")) == ["Bobur Karimov", "Sinov Bemor"]
    assert names(await get(source="google")) == ["Vali Soliyev"]
    assert names(await get(tag="tekshirish-kerak")) == ["Bobur Karimov"]
    assert names(await get(has_phone="false")) == ["Bobur Karimov"]
    assert "Bobur Karimov" not in names(await get(has_phone="true"))
    assert names(await get(category="alopecia_androgenic")) == ["Bobur Karimov"]
    assert names(await get(sort="last_visit"))[:2] == ["Aliyeva Dilnoza", "Bobur Karimov"]
    assert names(await get(sort="birth_date"))[:2] == ["Vali Soliyev", "Aliyeva Dilnoza"]
    assert (await get(sort="nope")).status_code == 422

    # a booked visit shows in the list and sorts it
    body = {**booking(clinic, at(next_monday(), 9)), "patient_id": str(ids["Vali Soliyev"])}
    assert (await client.post("/api/appointments", json=body, headers=op)).status_code == 201
    listed = (await get(sort="next_visit")).json()["items"]
    assert listed[0]["full_name"] == "Vali Soliyev" and listed[0]["next_visit_at"]
    assert listed[0]["source"] == "google" and listed[0]["categories"] == []
    bobur = next(x for x in listed if x["full_name"] == "Bobur Karimov")
    assert bobur["categories"] == ["alopecia_androgenic"] and bobur["next_visit_at"] is None

    tags = (await client.get("/api/patients/meta/tags", headers=op)).json()
    assert {"tag": "tekshirish-kerak", "count": 1} in tags and {"tag": "vip", "count": 1} in tags


# --- patient card ------------------------------------------------------------------------------


async def test_categories_are_edited_on_the_card(client: AsyncClient, op: dict) -> None:
    ids = await _patients()
    pid = ids["Bobur Karimov"]
    url = f"/api/patients/{pid}/categories"
    added = await client.post(url, json={"code": "acne"}, headers=op)
    assert added.status_code == 200
    assert added.json()["categories"] == ["acne", "alopecia_androgenic"]
    again = await client.post(url, json={"code": "acne"}, headers=op)  # idempotent
    assert len([c for c in again.json()["conditions"] if c["category_code"] == "acne"]) == 1
    unknown = await client.post(url, json={"code": "nope"}, headers=op)
    assert unknown.status_code == 422 and unknown.json()["detail"] == "unknown_category"

    # re-applying the diagnosis mapping keeps what staff set by hand
    async with SessionLocal() as s:
        await diagnoses.apply(s)
        await s.commit()
    card = (await client.get(f"/api/patients/{pid}", headers=op)).json()
    assert "acne" in card["categories"]

    imported = await client.delete(f"{url}/alopecia_androgenic", headers=op)
    assert imported.status_code == 409 and imported.json()["detail"] == "category_from_import"
    removed = await client.delete(f"{url}/acne", headers=op)
    assert removed.json()["categories"] == ["alopecia_androgenic"]
    async with SessionLocal() as s:
        actions = list(
            await s.scalars(select(AuditLog.action).where(AuditLog.action == "patient.categories"))
        )
    assert len(actions) == 3


async def test_card_shows_the_first_contact(client: AsyncClient, op: dict) -> None:
    ids = await _patients()
    card = (await client.get(f"/api/patients/{ids['Bobur Karimov']}", headers=op)).json()
    assert card["first_contact_at"] is None  # imported, never got in touch since
    # a cold-base number that called in: its first contact is that inquiry
    await new_lead(client, op, phone="904000004", source="instagram")
    card = (await client.get(f"/api/patients/{ids['Sovuq Raqam']}", headers=op)).json()
    assert card["first_contact_channel"] == "manual" and card["first_contact_at"]

    created = await client.post(
        "/api/patients",
        json={"full_name": "Yangi Bemor", "source": "google", "phones": [{"number": "905550001"}]},
        headers=op,
    )
    card = (await client.get(f"/api/patients/{created.json()['id']}", headers=op)).json()
    assert card["first_contact_channel"] == "registered"


async def test_timeline_items_point_to_what_they_open(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    body = booking(clinic, at(next_monday(), 11))
    appt = (await client.post("/api/appointments", json=body, headers=op)).json()
    events = (await client.get(f"/api/patients/{clinic['patient']}/timeline", headers=op)).json()
    [item] = [e for e in events if e["kind"] == "appointment"]
    assert item["appointment_id"] == appt["id"]


# --- the queue: script context, attempts, completed tab ------------------------------------------


async def _open(type_: TaskType) -> list[Task]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(select(Task).where(Task.type == type_, Task.status == TaskStatus.OPEN))
        )


async def test_task_carries_what_its_script_placeholders_need(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    body = booking(clinic, at(next_monday(), 9), doctor="d2")
    appt = (await client.post("/api/appointments", json=body, headers=op)).json()
    async with SessionLocal() as s:
        await tasks_service.create_task(
            s, TaskType.CONFIRM_VISIT, due_at=clinic_time.now(),
            patient_id=uuid.UUID(clinic["patient"]), appointment_id=uuid.UUID(appt["id"]),
        )  # fmt: skip
        await s.commit()
    resp = await client.post(
        "/api/recommendations",
        json={
            "patient_id": clinic["patient"], "due_date": (date.today() + timedelta(days=1)).isoformat(),
            "service_id": clinic["laser"], "appointment_id": appt["id"],
        },
        headers=bearer(await login(client, await _registrar())),
    )  # fmt: skip
    assert resp.status_code == 201, resp.text

    queue = (await client.get("/api/tasks", params={"view": "all"}, headers=op)).json()
    confirm = next(t for t in queue if t["type"] == "confirm_visit")
    assert confirm["context"] == {
        "doctor_uz": "Doktor B", "doctor_ru": "Доктор Б",
        "services_uz": "Konsultatsiya", "services_ru": "Консультация",
        "branch_uz": "Farg'ona", "branch_ru": "Фергана",
    }  # fmt: skip
    assert confirm["appointment_at"]
    repeat = next(t for t in queue if t["type"] == "repeat_visit")
    assert repeat["context"]["doctor_uz"] == "Doktor B"
    assert repeat["context"]["services_uz"] == "Lazer epilyatsiya"
    assert repeat["recommendation_due"] == (date.today() + timedelta(days=1)).isoformat()


async def _registrar() -> str:
    await make_user("reg1", Role.REGISTRAR)
    return "reg1"


async def test_campaign_filter_and_names(client: AsyncClient, clinic: dict, op: dict) -> None:
    async with SessionLocal() as s:
        camp = Campaign(name="Alopesiya kuzi", segment={})
        s.add(camp)
        await s.flush()
        await tasks_service.create_task(
            s, TaskType.CAMPAIGN, due_at=clinic_time.now(),
            patient_id=uuid.UUID(clinic["patient"]), campaign_id=camp.id,
        )  # fmt: skip
        await tasks_service.create_task(
            s, TaskType.CALLBACK, due_at=clinic_time.now(), patient_id=uuid.UUID(clinic["patient"])
        )
        await s.commit()
    all_tasks = (await client.get("/api/tasks", headers=op)).json()
    assert len(all_tasks) == 2
    only = (await client.get("/api/tasks", params={"campaign_id": str(camp.id)}, headers=op)).json()
    assert [t["campaign_name"] for t in only] == ["Alopesiya kuzi"]
    summary = (await client.get("/api/tasks/summary", headers=op)).json()
    assert summary["campaigns"] == [{"id": str(camp.id), "name": "Alopesiya kuzi", "open": 1}]


async def test_attempt_history_and_completed_tab(
    client: AsyncClient, clinic: dict, op: dict, sup: dict
) -> None:
    await make_user("op2", Role.OPERATOR)
    op2 = bearer(await login(client, "op2"))
    ids = []
    async with SessionLocal() as s:
        for _ in range(3):
            p = Patient(full_name="Navbat", search_key="navbat", kind=PatientKind.ACTIVE, tags=[])
            s.add(p)
            await s.flush()
            await tasks_service.create_task(
                s, TaskType.CALLBACK, due_at=clinic_time.now(), patient_id=p.id
            )
        await s.commit()
    queue = (await client.get("/api/tasks", headers=op)).json()
    ids = [t["id"] for t in queue]
    await client.post(f"/api/tasks/{ids[0]}/result", json={"outcome": "no_answer"}, headers=op)
    await client.post(
        f"/api/tasks/{ids[0]}/result", json={"outcome": "done", "note": "gaplashildi"}, headers=op2
    )
    await client.post(f"/api/tasks/{ids[1]}/result", json={"outcome": "done"}, headers=op)
    await client.post(f"/api/tasks/{ids[2]}/cancel", json={"reason": "dublikat"}, headers=sup)

    attempts = (await client.get(f"/api/tasks/{ids[0]}/attempts", headers=op)).json()
    assert [(a["outcome"], a["user_name"]) for a in attempts] == [
        ("done", "Op2"), ("no_answer", "Op1"),
    ]  # fmt: skip

    done = (await client.get("/api/tasks/done", headers=op)).json()
    assert done["total"] == 3
    assert {(b["name"], b["count"]) for b in done["by_user"]} == {
        ("Op1", 1), ("Op2", 1), ("Sup1", 1),
    }  # fmt: skip
    cancelled = next(t for t in done["items"] if t["id"] == ids[2])
    assert cancelled["status"] == "cancelled" and cancelled["cancel_reason"] == "dublikat"
    assert cancelled["completed_by_name"] == "Sup1"
    op1_id = next(b["user_id"] for b in done["by_user"] if b["name"] == "Op1")
    mine = (await client.get("/api/tasks/done", params={"user_id": op1_id}, headers=op)).json()
    assert [t["id"] for t in mine["items"]] == [ids[1]]

    # a task closed last week is in the 7-day view only
    async with SessionLocal() as s:
        await s.execute(
            update(Task)
            .where(Task.id == uuid.UUID(ids[1]))
            .values(completed_at=clinic_time.now() - timedelta(days=3))
        )
        await s.commit()
    today = (await client.get("/api/tasks/done", headers=op)).json()
    week = (await client.get("/api/tasks/done", params={"period": "week"}, headers=op)).json()
    assert today["total"] == 2 and week["total"] == 3


# --- supervisor actions ------------------------------------------------------------------------


async def test_supervisor_moves_reprioritises_and_cancels_tasks(
    client: AsyncClient, clinic: dict, op: dict, sup: dict
) -> None:
    async with SessionLocal() as s:
        await tasks_service.create_task(
            s, TaskType.CALLBACK, due_at=clinic_time.now(), patient_id=uuid.UUID(clinic["patient"])
        )
        await s.commit()
    [task] = await _open(TaskType.CALLBACK)
    url = f"/api/tasks/{task.id}"
    later = (clinic_time.now() + timedelta(days=2)).isoformat()

    # operators work the queue; only the call-center lead reshapes it
    assert (await client.patch(url, json={"priority": 3}, headers=op)).status_code == 403
    assert (
        await client.post(f"{url}/cancel", json={"reason": "kerak emas"}, headers=op)
    ).status_code == 403

    moved = (await client.patch(url, json={"due_at": later, "priority": 3}, headers=sup)).json()
    assert moved["priority"] == 3
    assert datetime.fromisoformat(moved["due_at"]) == datetime.fromisoformat(later)
    today = (await client.get("/api/tasks", headers=op)).json()
    assert today == []  # moved out of today's queue
    bad = await client.patch(url, json={"priority": 0}, headers=sup)
    assert bad.status_code == 422
    naive = await client.patch(url, json={"due_at": "2026-10-01T10:00:00"}, headers=sup)
    assert naive.status_code == 422  # a time without a zone is ambiguous

    short = await client.post(f"{url}/cancel", json={"reason": "x"}, headers=sup)
    assert short.status_code == 422
    cancelled = (
        await client.post(f"{url}/cancel", json={"reason": "Bemor o'zi keldi"}, headers=sup)
    ).json()
    assert cancelled["status"] == "cancelled" and cancelled["cancel_reason"] == "Bemor o'zi keldi"
    again = await client.post(f"{url}/cancel", json={"reason": "yana bir bor"}, headers=sup)
    assert again.status_code == 400 and again.json()["detail"] == "task_closed"
    closed = await client.patch(url, json={"priority": 5}, headers=sup)
    assert closed.status_code == 400

    async with SessionLocal() as s:
        actions = sorted(
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(task.id)))
        )
    assert actions == ["task.cancel", "task.update"]
