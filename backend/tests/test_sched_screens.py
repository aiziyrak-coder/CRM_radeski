"""Registrar / doctor screens and catalog settings (TZ 4.2, 4.3): resources, week views,
no-show reasons, recommendations the doctor edits, patient context, doctor<->service links,
bulk service edits, schedule copy and the catalog sync log."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.catalog import sync as sync_module
from app.modules.catalog.models import (
    Branch,
    CatalogSyncRun,
    Doctor,
    Resource,
    ResourceKind,
    Service,
    SyncStatus,
)
from app.modules.patients.models import PatientCondition
from app.modules.tasks.models import Task, TaskStatus, TaskType
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import TZ, at, booking, next_monday
from tests.test_catalog import site


async def _admin(client: AsyncClient) -> dict:
    await make_user("admin", Role.ADMIN)
    return bearer(await login(client, "admin"))


async def _doctor(client: AsyncClient, doctor_id: str, username: str = "doc1") -> dict:
    user = await make_user(username, Role.DOCTOR)
    async with SessionLocal() as s:
        (await s.get(Doctor, uuid.UUID(doctor_id))).user_id = user.id
        await s.commit()
    return bearer(await login(client, username))


async def _book(client: AsyncClient, clinic: dict, op: dict, hh: int, **kw) -> dict:
    resp = await client.post(
        "/api/appointments", json=booking(clinic, at(next_monday(), hh), **kw), headers=op
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- statuses --------------------------------------------------------------------------------


async def test_no_show_needs_a_reason_and_coming_late_clears_it(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    appt = await _book(client, clinic, op, 9)
    url = f"/api/appointments/{appt['id']}/status"
    resp = await client.post(url, json={"status": "no_show"}, headers=op)
    assert resp.status_code == 400 and resp.json()["detail"] == "reason_required"
    resp = await client.post(url, json={"status": "no_show", "reason": "  "}, headers=op)
    assert resp.status_code == 400

    resp = await client.post(url, json={"status": "no_show", "reason": "no_answer"}, headers=op)
    assert resp.status_code == 200 and resp.json()["cancel_reason"] == "no_answer"
    resp = await client.post(url, json={"status": "arrived"}, headers=op)
    assert resp.status_code == 200 and resp.json()["cancel_reason"] is None


async def test_appointment_shows_author_resource_and_reschedule_links(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    laser = await _book(client, clinic, op, 10, doctor="d2", service="laser")
    assert laser["resource_name"] == "Lazer 1" and laser["resource_kind"] == "device"
    assert laser["created_by_name"] == "Op1" and laser["created_at"]

    old = await _book(client, clinic, op, 9)
    resp = await client.post(
        f"/api/appointments/{old['id']}/reschedule",
        json={"starts_at": at(next_monday(), 11)},
        headers=op,
    )
    new = resp.json()
    assert new["rescheduled_from_id"] == old["id"]
    assert datetime.fromisoformat(new["rescheduled_from_starts_at"]) == datetime.fromisoformat(
        old["starts_at"]
    )
    day = (
        await client.get(
            "/api/appointments/day",
            params={"date": next_monday().isoformat(), "branch_id": clinic["branch"]},
            headers=op,
        )
    ).json()
    moved = next(a for a in day if a["id"] == old["id"])
    assert moved["status"] == "rescheduled" and moved["rescheduled_to_id"] == new["id"]


# --- rooms and devices -----------------------------------------------------------------------


async def test_registrar_puts_visits_into_rooms_without_double_booking(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    async with SessionLocal() as s:
        room = Resource(
            branch_id=uuid.UUID(clinic["branch"]), name="1-xona", kind=ResourceKind.ROOM
        )
        laser2 = Resource(
            branch_id=uuid.UUID(clinic["branch"]),
            name="Lazer 2",
            kind=ResourceKind.DEVICE,
            device_type="laser_epilation",
        )
        other_branch = Branch(name_uz="Qo'qon", name_ru="Коканд")
        s.add_all([room, laser2, other_branch])
        await s.flush()
        foreign_room = Resource(branch_id=other_branch.id, name="X", kind=ResourceKind.ROOM)
        s.add(foreign_room)
        await s.commit()
    a = await _book(client, clinic, op, 9)
    b = await _book(client, clinic, op, 9, doctor="d2")
    laser = await _book(client, clinic, op, 11, doctor="d2", service="laser")

    def put(appt: dict, resource_id: object) -> object:
        return client.post(
            f"/api/appointments/{appt['id']}/resource",
            json={"resource_id": str(resource_id) if resource_id else None},
            headers=op,
        )

    resp = await put(a, room.id)
    assert resp.status_code == 200 and resp.json()["resource_name"] == "1-xona"
    clash = await put(b, room.id)  # same time, same room
    assert clash.status_code == 409 and clash.json()["detail"] == "resource_busy"
    assert (await put(b, foreign_room.id)).json()["detail"] == "resource_not_found"
    # a laser visit stays on a laser: another laser is fine, a room or "none" is not
    assert (await put(laser, room.id)).json()["detail"] == "wrong_device"
    assert (await put(laser, None)).json()["detail"] == "device_required"
    resp = await put(laser, laser2.id)
    assert resp.status_code == 200 and resp.json()["resource_name"] == "Lazer 2"
    resp = await put(a, None)
    assert resp.status_code == 200 and resp.json()["resource_id"] is None

    doc = await _doctor(client, clinic["d1"])
    assert (await client.post(
        f"/api/appointments/{a['id']}/resource", json={"resource_id": None}, headers=doc
    )).status_code == 403  # fmt: skip


# --- week views -------------------------------------------------------------------------------


async def test_week_views_for_the_schedule_and_the_doctor(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    monday = next_monday()
    await _book(client, clinic, op, 9)
    await _book(client, clinic, op, 10, doctor="d2")
    params = {"date_from": monday.isoformat(), "branch_id": clinic["branch"]}

    week = (await client.get("/api/appointments/range", params=params, headers=op)).json()
    assert len(week) == 2
    doc = await _doctor(client, clinic["d1"])
    own = (await client.get("/api/appointments/range", params=params, headers=doc)).json()
    assert [a["doctor_id"] for a in own] == [clinic["d1"]]

    days = (await client.get("/api/schedule/range", params=params, headers=op)).json()
    assert [d["date"] for d in days] == [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    assert {c["doctor_id"] for c in days[0]["doctors"]} == {clinic["d1"], clinic["d2"]}
    assert days[1]["doctors"] == []  # nobody works on Tuesday
    window = days[0]["doctors"][0]["windows"][0]
    assert datetime.fromisoformat(window["starts_at"]).astimezone(TZ).time() == time(9)


# --- weekly schedule: breaks, copying, absences -------------------------------------------------


async def test_weekly_schedule_with_a_break_and_copying_it(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    await make_user("sup", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup"))
    rows = [
        {"branch_id": clinic["branch"], "weekday": 0, "start_time": "09:00", "end_time": "13:00"},
        {"branch_id": clinic["branch"], "weekday": 0, "start_time": "12:00", "end_time": "18:00"},
    ]
    url = f"/api/schedule/doctors/{clinic['d1']}/weekly"
    resp = await client.put(url, json={"rows": rows}, headers=sup)
    assert resp.status_code == 422 and "rows_overlap" in resp.text

    rows[1]["start_time"] = "14:00"  # 13:00-14:00 is the lunch break
    assert (await client.put(url, json={"rows": rows}, headers=sup)).status_code == 200
    slots = (
        await client.get(
            "/api/appointments/slots",
            params={
                "service_ids": clinic["consult"],
                "branch_id": clinic["branch"],
                "doctor_id": clinic["d1"],
                "date_from": next_monday().isoformat(),
                "limit": 20,
            },
            headers=op,
        )
    ).json()
    hours = {datetime.fromisoformat(s["starts_at"]).astimezone(TZ).hour for s in slots}
    assert 13 not in hours and 14 in hours

    resp = await client.post(
        f"/api/schedule/doctors/{clinic['d1']}/copy",
        json={"doctor_ids": [clinic["tri"], clinic["d1"]]},
        headers=sup,
    )
    assert resp.status_code == 200 and resp.json() == {"doctors": 1, "rows": 2}
    copied = (await client.get(f"/api/schedule/doctors/{clinic['tri']}", headers=sup)).json()
    assert [(r["start_time"], r["end_time"]) for r in copied["rows"]] == [
        ("09:00:00", "13:00:00"),
        ("14:00:00", "18:00:00"),
    ]
    resp = await client.post(
        f"/api/schedule/doctors/{clinic['d1']}/copy",
        json={"doctor_ids": [clinic["tri"]]},
        headers=op,
    )
    assert resp.status_code == 403


async def test_absence_has_a_kind(client: AsyncClient, clinic: dict) -> None:
    await make_user("sup", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup"))
    monday = next_monday().isoformat()
    resp = await client.post(
        f"/api/schedule/doctors/{clinic['d1']}/absences",
        json={"date_from": monday, "date_to": monday, "kind": "sick"},
        headers=sup,
    )
    assert resp.status_code == 201 and resp.json()["kind"] == "sick"
    listed = (await client.get(f"/api/schedule/doctors/{clinic['d1']}", headers=sup)).json()
    assert listed["absences"][0]["kind"] == "sick"
    resp = await client.post(
        f"/api/schedule/doctors/{clinic['d1']}/absences",
        json={"date_from": monday, "date_to": monday, "kind": "holiday"},
        headers=sup,
    )
    assert resp.status_code == 422


# --- recommendations ----------------------------------------------------------------------------


async def test_doctor_edits_and_withdraws_own_recommendation(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    appt = await _book(client, clinic, op, 9)
    doc = await _doctor(client, clinic["d1"])
    due = (datetime.now(UTC).date() + timedelta(days=60)).isoformat()
    resp = await client.post(
        "/api/recommendations",
        json={"patient_id": clinic["patient"], "appointment_id": appt["id"], "due_date": due},
        headers=doc,
    )
    rec = resp.json()
    assert rec["can_edit"] is True and rec["doctor_name"] == "Doktor A"

    later = (datetime.now(UTC).date() + timedelta(days=90)).isoformat()
    resp = await client.patch(
        f"/api/recommendations/{rec['id']}",
        json={"due_date": later, "service_id": clinic["consult"], "note": "nazorat"},
        headers=doc,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["due_date"] == later and body["service_name_uz"] == "Konsultatsiya"
    async with SessionLocal() as s:
        task = await s.scalar(select(Task).where(Task.recommendation_id == uuid.UUID(rec["id"])))
        assert task.type is TaskType.REPEAT_VISIT and task.note == "nazorat"
        # the call comes repeat_visit_lead_days (3) before the new date
        assert task.due_at.astimezone(TZ).date() == date.fromisoformat(later) - timedelta(days=3)

    # another doctor can't touch it
    other = await _doctor(client, clinic["d2"], "doc2")
    url = f"/api/recommendations/{rec['id']}"
    assert (await client.patch(url, json={"note": "x"}, headers=other)).status_code == 403

    resp = await client.post(f"{url}/dismiss", headers=doc)
    assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
    assert resp.json()["can_edit"] is False
    async with SessionLocal() as s:
        task = await s.scalar(select(Task).where(Task.recommendation_id == uuid.UUID(rec["id"])))
        assert task.status is TaskStatus.CANCELLED
    resp = await client.patch(url, json={"note": "y"}, headers=doc)
    assert resp.status_code == 409 and resp.json()["detail"] == "recommendation_closed"


async def test_patient_context_for_the_doctor(client: AsyncClient, clinic: dict, op: dict) -> None:
    appt = await _book(client, clinic, op, 9)
    async with SessionLocal() as s:
        s.add(
            PatientCondition(
                patient_id=uuid.UUID(clinic["patient"]),
                raw_text="Псориаз",
                category_code="psoriasis",
                source="import:main",
            )
        )
        await s.commit()
    doc = await _doctor(client, clinic["d1"])
    await client.post(
        "/api/recommendations",
        json={
            "patient_id": clinic["patient"],
            "appointment_id": appt["id"],
            "due_date": (datetime.now(UTC).date() + timedelta(days=30)).isoformat(),
        },
        headers=doc,
    )
    resp = await client.get(f"/api/patient-context/{clinic['patient']}", headers=doc)
    assert resp.status_code == 200, resp.text
    ctx = resp.json()
    assert ctx["patient"]["full_name"] == "Sinov Bemor"
    assert ctx["conditions"][0]["category_code"] == "psoriasis"
    assert ctx["conditions"][0]["category_name_uz"]
    assert [v["id"] for v in ctx["visits"]] == [appt["id"]]
    assert len(ctx["recommendations"]) == 1 and ctx["recommendations"][0]["can_edit"]
    async with SessionLocal() as s:
        assert await s.scalar(select(AuditLog).where(AuditLog.action == "patient.context"))

    stranger = await _doctor(client, clinic["tri"], "doc3")
    resp = await client.get(f"/api/patient-context/{clinic['patient']}", headers=stranger)
    assert resp.status_code == 403


# --- catalog: doctor <-> service, services, device types -----------------------------------------


async def test_doctor_service_links_decide_who_is_offered(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    admin = await _admin(client)
    params = {
        "service_ids": clinic["consult"],
        "branch_id": clinic["branch"],
        "date_from": next_monday().isoformat(),
    }

    async def offered(doctor: str) -> bool:
        slots = await client.get(
            "/api/appointments/slots", params={**params, "doctor_id": clinic[doctor]}, headers=op
        )
        return bool(slots.json())

    assert await offered("d1") and await offered("d2")  # both dermatologists, by specialty

    url = f"/api/catalog/doctors/{clinic['d2']}/services"
    resp = await client.put(url, json={"service_ids": [clinic["consult"]]}, headers=admin)
    assert resp.status_code == 200
    links = (await client.get("/api/catalog/doctor-services", headers=op)).json()
    assert links == [{"doctor_id": clinic["d2"], "service_id": clinic["consult"]}]
    assert await offered("d2") and not await offered("d1")  # explicit links win

    missing = str(uuid.uuid4())
    resp = await client.put(url, json={"service_ids": [missing]}, headers=admin)
    assert resp.status_code == 404
    assert (await client.put(url, json={"service_ids": []}, headers=op)).status_code == 403
    assert (await client.put(url, json={"service_ids": []}, headers=admin)).json() == []


async def test_service_duration_filter_bulk_edit_and_device_types(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    admin = await _admin(client)
    missing = (
        await client.get("/api/catalog/services", params={"duration_missing": True}, headers=op)
    ).json()
    assert missing["total"] == 2  # nobody has set a real duration yet

    resp = await client.patch(
        f"/api/catalog/services/{clinic['consult']}", json={"duration_min": 20}, headers=admin
    )
    assert resp.json()["duration_confirmed"] is True
    missing = (
        await client.get("/api/catalog/services", params={"duration_missing": True}, headers=op)
    ).json()
    assert [s["id"] for s in missing["items"]] == [clinic["laser"]]

    resp = await client.post(
        "/api/catalog/services/bulk",
        json={"service_ids": [clinic["consult"], clinic["laser"]], "duration_min": 45},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.json() == {"updated": 2}
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(Service)))
        assert {r.duration_min for r in rows} == {45} and all(r.duration_confirmed for r in rows)
    resp = await client.post(
        "/api/catalog/services/bulk",
        json={"service_ids": [clinic["consult"]], "device_type": "co2_laser"},
        headers=admin,
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/api/catalog/services/bulk", json={"service_ids": [clinic["consult"]]}, headers=admin
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/api/catalog/services/bulk",
        json={"service_ids": [clinic["consult"]], "duration_min": 30},
        headers=op,
    )
    assert resp.status_code == 403

    types = (await client.get("/api/catalog/device-types", headers=op)).json()
    assert types == [
        {"device_type": "co2_laser", "resources": 0, "services": 1},
        {"device_type": "laser_epilation", "resources": 1, "services": 1},
    ]
    filtered = (
        await client.get("/api/catalog/services", params={"device_type": "co2_laser"}, headers=op)
    ).json()
    assert [s["id"] for s in filtered["items"]] == [clinic["consult"]]


async def test_resource_can_be_renamed_and_a_room_has_no_device_type(
    client: AsyncClient, clinic: dict
) -> None:
    admin = await _admin(client)
    body = {"branch_id": clinic["branch"], "name": "3-xona", "kind": "room", "device_type": "x_y"}
    created = (await client.post("/api/catalog/resources", json=body, headers=admin)).json()
    assert created["device_type"] is None
    resp = await client.put(
        f"/api/catalog/resources/{created['id']}",
        json={**body, "name": "Kosmetologiya xonasi"},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.json()["name"] == "Kosmetologiya xonasi"
    resp = await client.put(
        f"/api/catalog/resources/{created['id']}",
        json={**body, "kind": "device", "device_type": None},
        headers=admin,
    )
    assert resp.status_code == 422 and resp.json()["detail"] == "device_type_required"


# --- catalog sync log ----------------------------------------------------------------------------


async def test_catalog_sync_runs_are_recorded(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _admin(client)
    assert (await client.get("/api/catalog/sync", headers=admin)).json() == {
        "last": None,
        "last_ok": None,
    }

    async def good() -> dict:
        return {n: site(n) for n in ("branches", "doctors", "services", "prices")}

    monkeypatch.setattr(sync_module, "fetch_site_data", good)
    resp = await client.post("/api/catalog/sync", headers=admin)
    assert resp.status_code == 200 and resp.json()["branches_created"] == 2

    async def down() -> dict:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(sync_module, "fetch_site_data", down)
    resp = await client.post("/api/catalog/sync", headers=admin)
    assert resp.status_code == 502

    state = (await client.get("/api/catalog/sync", headers=admin)).json()
    assert state["last"]["status"] == "failed" and "ConnectError" in state["last"]["error"]
    assert state["last_ok"]["status"] == "ok" and state["last_ok"]["trigger"] == "manual"
    assert state["last_ok"]["counts"]["branches_created"] == 2
    async with SessionLocal() as s:
        runs = list(await s.scalars(select(CatalogSyncRun)))
        assert sorted(r.status for r in runs) == [SyncStatus.FAILED, SyncStatus.OK]
        assert await s.scalar(select(Branch.id).limit(1))  # the good sync was kept
