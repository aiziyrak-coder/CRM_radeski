"""Scheduling: working hours, double-booking, devices, course intervals, statuses."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.catalog.models import (
    Branch,
    Doctor,
    Resource,
    ResourceKind,
    Service,
    ServiceCategory,
)
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.scheduling.models import DoctorSchedule
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user

TZ = ZoneInfo("Asia/Tashkent")


def next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7) + timedelta(days=7)


def at(day: date, hh: int, mm: int = 0) -> str:
    return datetime.combine(day, time(hh, mm), TZ).isoformat()


@pytest.fixture
async def clinic() -> dict:
    """Branch, two dermatologists (Mon 09-13), one trichologist, a laser device, services."""
    async with SessionLocal() as s:
        branch = Branch(name_uz="Farg'ona", name_ru="Фергана", is_main=True)
        derm = ServiceCategory(
            site_id="dermatologiya", name_uz="Derm", name_ru="Derm", specialty="dermatologist"
        )
        cosm = ServiceCategory(
            site_id="laser", name_uz="Lazer", name_ru="Лазер", specialty="cosmetologist"
        )
        s.add_all([branch, derm, cosm])
        await s.flush()
        d1 = Doctor(
            name_uz="Doktor A", name_ru="Доктор А", specialties=["dermatologist"], sort_order=1
        )
        d2 = Doctor(
            name_uz="Doktor B",
            name_ru="Доктор Б",
            specialties=["dermatologist", "cosmetologist"],
            sort_order=2,
        )
        tri = Doctor(
            name_uz="Trixolog", name_ru="Трихолог", specialties=["trichologist"], sort_order=3
        )
        consult = Service(
            name_uz="Konsultatsiya",
            name_ru="Консультация",
            category_id=derm.id,
            duration_min=30,
            is_consultation=True,
        )
        laser = Service(
            name_uz="Lazer epilyatsiya",
            name_ru="Лазерная эпиляция",
            category_id=cosm.id,
            duration_min=60,
            device_type="laser_epilation",
            min_interval_days=30,
        )
        s.add_all([d1, d2, tri, consult, laser])
        await s.flush()
        s.add(
            Resource(
                branch_id=branch.id,
                name="Lazer 1",
                kind=ResourceKind.DEVICE,
                device_type="laser_epilation",
            )
        )
        for doc in (d1, d2):
            s.add(
                DoctorSchedule(
                    doctor_id=doc.id,
                    branch_id=branch.id,
                    weekday=0,
                    start_time=time(9),
                    end_time=time(13),
                )
            )
        patient = Patient(
            full_name="Sinov Bemor",
            search_key=search_key("Sinov Bemor"),
            kind=PatientKind.LEGACY,
            tags=[],
            phones=[PatientPhone(number="+998900000001", is_primary=True)],
        )
        s.add(patient)
        await s.commit()
        return {
            "branch": str(branch.id), "d1": str(d1.id), "d2": str(d2.id), "tri": str(tri.id),
            "consult": str(consult.id), "laser": str(laser.id), "patient": str(patient.id),
        }  # fmt: skip


@pytest.fixture
async def op(client: AsyncClient) -> dict:
    await make_user("op1", Role.OPERATOR)
    return bearer(await login(client, "op1"))


def booking(c: dict, starts_at: str, doctor: str = "d1", service: str = "consult", **extra) -> dict:
    return {
        "patient_id": c["patient"],
        "branch_id": c["branch"],
        "doctor_id": c[doctor],
        "service_ids": [c[service]],
        "starts_at": starts_at,
        **extra,
    }


async def test_slot_finder_offers_earliest_distinct_times(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    resp = await client.get(
        "/api/appointments/slots",
        params={
            "service_ids": clinic["consult"],
            "branch_id": clinic["branch"],
            "date_from": day.isoformat(),
        },
        headers=op,
    )
    assert resp.status_code == 200
    starts = [s["starts_at"] for s in resp.json()]
    assert starts == [datetime.combine(day, time(9, m), TZ).isoformat() for m in (0, 15, 30)], (
        "earliest three 15-minute steps"
    )


async def test_slot_finder_respects_specialty_and_part_of_day(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    params = {
        "service_ids": clinic["consult"],
        "branch_id": clinic["branch"],
        "date_from": day.isoformat(),
        "part": "afternoon",
        "limit": 20,
    }
    slots = (await client.get("/api/appointments/slots", params=params, headers=op)).json()
    assert slots and all(s["doctor_id"] != clinic["tri"] for s in slots)
    assert all(12 <= datetime.fromisoformat(s["starts_at"]).astimezone(TZ).hour < 16 for s in slots)


async def test_booking_and_double_booking(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    first = await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "scheduled" and body["patient_name"] == "Sinov Bemor"
    assert body["ends_at"] == datetime.combine(day, time(9, 30), TZ).isoformat()

    clash = await client.post("/api/appointments", json=booking(clinic, at(day, 9, 15)), headers=op)
    assert clash.status_code == 409 and clash.json()["detail"] == "slot_taken"

    # the other doctor is free at the same time
    other = await client.post(
        "/api/appointments", json=booking(clinic, at(day, 9, 15), doctor="d2"), headers=op
    )
    assert other.status_code == 201

    # the taken time disappears from the slot finder for doctor A
    slots = (
        await client.get(
            "/api/appointments/slots",
            params={
                "service_ids": clinic["consult"],
                "branch_id": clinic["branch"],
                "doctor_id": clinic["d1"],
                "date_from": day.isoformat(),
            },
            headers=op,
        )
    ).json()
    assert slots[0]["starts_at"] == datetime.combine(day, time(9, 30), TZ).isoformat()


async def test_outside_working_hours(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    late = booking(clinic, at(day, 12, 45))  # 30 min would end at 13:15
    resp = await client.post("/api/appointments", json=late, headers=op)
    assert resp.status_code == 409 and resp.json()["detail"] == "outside_schedule"

    forced = await client.post(
        "/api/appointments", json={**late, "allow_outside_hours": True}, headers=op
    )
    assert forced.status_code == 403  # operators can't override

    await make_user("reg1", Role.REGISTRAR)
    reg = bearer(await login(client, "reg1"))
    assert (
        await client.post(
            "/api/appointments", json={**late, "allow_outside_hours": True}, headers=reg
        )
    ).status_code == 201


async def test_device_is_a_shared_bottleneck(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    a = await client.post(
        "/api/appointments",
        json=booking(clinic, at(day, 10), doctor="d2", service="laser"),
        headers=op,
    )
    assert a.status_code == 201 and a.json()["resource_id"]

    # a second laser patient can't be booked at an overlapping time: the only laser is busy,
    # even though doctor B is the only cosmetologist and is also busy
    busy = await client.post(
        "/api/appointments",
        json=booking(clinic, at(day, 10, 30), doctor="d2", service="laser"),
        headers=op,
    )
    assert busy.status_code == 409


async def test_course_interval_pushes_next_session(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    await client.post(
        "/api/appointments",
        json=booking(clinic, at(day, 10), doctor="d2", service="laser"),
        headers=op,
    )

    slots = (
        await client.get(
            "/api/appointments/slots",
            params={
                "service_ids": clinic["laser"],
                "branch_id": clinic["branch"],
                "patient_id": clinic["patient"],
                "date_from": day.isoformat(),
                "days": 60,
            },
            headers=op,
        )
    ).json()
    assert slots
    first = datetime.fromisoformat(slots[0]["starts_at"]).astimezone(TZ).date()
    assert first >= day + timedelta(days=30)


async def test_status_flow_and_reschedule(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    url = f"/api/appointments/{appt['id']}"

    assert (
        await client.post(f"{url}/status", json={"status": "confirmed"}, headers=op)
    ).status_code == 200
    no_reason = await client.post(f"{url}/status", json={"status": "cancelled"}, headers=op)
    assert no_reason.status_code == 400 and no_reason.json()["detail"] == "reason_required"

    # move 30 minutes later on the same doctor: the old slot must not block the new one
    moved = await client.post(f"{url}/reschedule", json={"starts_at": at(day, 9, 15)}, headers=op)
    assert moved.status_code == 200, moved.text
    new = moved.json()
    assert new["rescheduled_from_id"] == appt["id"] and new["status"] == "scheduled"

    history = (
        await client.get(f"/api/appointments/patient/{clinic['patient']}", headers=op)
    ).json()
    assert {h["status"] for h in history} == {"rescheduled", "scheduled"}

    bad = await client.post(f"{url}/status", json={"status": "arrived"}, headers=op)
    assert bad.status_code == 400 and bad.json()["detail"] == "invalid_transition"


async def test_arrival_makes_patient_active(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    await client.post(
        f"/api/appointments/{appt['id']}/status", json={"status": "arrived"}, headers=op
    )

    card = (await client.get(f"/api/patients/{clinic['patient']}", headers=op)).json()
    assert card["kind"] == "active" and card["last_visit_at"]


async def test_doctor_day_and_recommendation(client: AsyncClient, clinic: dict, op: dict) -> None:
    doctor_user = await make_user("doc1", Role.DOCTOR)
    async with SessionLocal() as s:
        d1 = await s.get(Doctor, __import__("uuid").UUID(clinic["d1"]))
        d1.user_id = doctor_user.id
        await s.commit()
    doc = bearer(await login(client, "doc1"))

    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()

    mine = (
        await client.get("/api/appointments/my-day", params={"date": day.isoformat()}, headers=doc)
    ).json()
    assert [a["id"] for a in mine] == [appt["id"]]

    # doctors mark their own patients seen, but can't cancel
    url = f"/api/appointments/{appt['id']}/status"
    assert (
        await client.post(url, json={"status": "cancelled", "reason": "x"}, headers=doc)
    ).status_code == 403
    assert (await client.post(url, json={"status": "arrived"}, headers=doc)).status_code == 200
    assert (await client.post(url, json={"status": "completed"}, headers=doc)).status_code == 200

    rec = await client.post(
        "/api/recommendations",
        json={
            "patient_id": clinic["patient"],
            "appointment_id": appt["id"],
            "due_date": (day + timedelta(days=14)).isoformat(),
            "note": "2 haftadan keyin nazorat",
        },
        headers=doc,
    )
    assert rec.status_code == 201 and rec.json()["doctor_id"] == clinic["d1"]

    assert (
        await client.post(
            "/api/recommendations",
            json={"patient_id": clinic["patient"], "due_date": day.isoformat()},
            headers=op,
        )
    ).status_code == 403


async def test_weekly_schedule_is_managed_by_supervisors(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    rows = {
        "rows": [
            {
                "branch_id": clinic["branch"],
                "weekday": 1,
                "start_time": "10:00",
                "end_time": "15:00",
            }
        ]
    }
    assert (
        await client.put(f"/api/schedule/doctors/{clinic['tri']}/weekly", json=rows, headers=op)
    ).status_code == 403

    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    resp = await client.put(f"/api/schedule/doctors/{clinic['tri']}/weekly", json=rows, headers=sup)
    assert resp.status_code == 200 and resp.json()["rows"][0]["weekday"] == 1

    bad = {
        "rows": [
            {
                "branch_id": clinic["branch"],
                "weekday": 1,
                "start_time": "15:00",
                "end_time": "10:00",
            }
        ]
    }
    assert (
        await client.put(f"/api/schedule/doctors/{clinic['tri']}/weekly", json=bad, headers=sup)
    ).status_code == 422


async def test_day_columns(client: AsyncClient, clinic: dict, op: dict) -> None:
    day = next_monday()
    cols = (
        await client.get(
            "/api/schedule/day",
            params={"date": day.isoformat(), "branch_id": clinic["branch"]},
            headers=op,
        )
    ).json()
    assert [c["doctor_name"] for c in cols] == ["Doktor A", "Doktor B"]
    assert cols[0]["windows"] == [{"starts_at": at(day, 9), "ends_at": at(day, 13)}]
    tuesday = (
        await client.get(
            "/api/schedule/day",
            params={"date": (day + timedelta(days=1)).isoformat(), "branch_id": clinic["branch"]},
            headers=op,
        )
    ).json()
    assert tuesday == []
