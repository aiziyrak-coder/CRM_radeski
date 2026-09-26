"""Scheduling: working hours, double-booking, devices, course intervals, statuses."""

import uuid
from datetime import datetime, time, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Branch, Doctor, DoctorService
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import TZ, at, booking, next_monday


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


async def test_reschedule_of_a_course_session_is_not_blocked_by_itself(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    appt = (
        await client.post(
            "/api/appointments",
            json=booking(clinic, at(day, 10), doctor="d2", service="laser"),
            headers=op,
        )
    ).json()
    params = {
        "service_ids": clinic["laser"],
        "branch_id": clinic["branch"],
        "patient_id": clinic["patient"],
        "date_from": day.isoformat(),
        "days": 60,
    }

    async def first_day(**extra: str) -> object:
        slots = (
            await client.get("/api/appointments/slots", params={**params, **extra}, headers=op)
        ).json()
        return datetime.fromisoformat(slots[0]["starts_at"]).astimezone(TZ).date()

    assert await first_day() >= day + timedelta(days=30)  # a second session must wait
    # moving the same session: it doesn't block itself
    assert await first_day(exclude_appointment_id=appt["id"]) == day

    # a booked session also blocks the days just before it
    week_before = (day - timedelta(days=7)).isoformat()
    assert await first_day(date_from=week_before) >= day + timedelta(days=30)

    # a cancelled session doesn't count
    await client.post(
        f"/api/appointments/{appt['id']}/status",
        json={"status": "cancelled", "reason": "x"},
        headers=op,
    )
    assert await first_day() == day


async def test_booking_checks_branch_and_doctor_services(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    wrong_doctor = await client.post(
        "/api/appointments", json=booking(clinic, at(day, 9), doctor="tri"), headers=op
    )
    assert wrong_doctor.status_code == 409
    assert wrong_doctor.json()["detail"] == "doctor_not_eligible"
    no_branch = await client.post(
        "/api/appointments",
        json={**booking(clinic, at(day, 9)), "branch_id": str(uuid.uuid4())},
        headers=op,
    )
    assert no_branch.status_code == 404 and no_branch.json()["detail"] == "branch_not_found"

    async with SessionLocal() as s:
        other_branch = Branch(name_uz="Ikkinchi filial", name_ru="Второй филиал")
        s.add(other_branch)
        await s.commit()
    await make_user("reg1", Role.REGISTRAR)
    reg = bearer(await login(client, "reg1"))
    elsewhere = await client.post(
        "/api/appointments",
        json={
            **booking(clinic, at(day, 9)),
            "branch_id": str(other_branch.id),
            "allow_outside_hours": True,
        },
        headers=reg,
    )
    assert elsewhere.status_code == 409
    assert elsewhere.json()["detail"] == "doctor_not_at_branch"

    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    moved = await client.post(
        f"/api/appointments/{appt['id']}/reschedule",
        json={"starts_at": at(day, 10), "doctor_id": clinic["tri"]},
        headers=op,
    )
    assert moved.status_code == 409 and moved.json()["detail"] == "doctor_not_eligible"


async def test_recommendation_must_match_the_appointment(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    doctor_user = await make_user("doc1", Role.DOCTOR)
    async with SessionLocal() as s:
        (await s.get(Doctor, uuid.UUID(clinic["d1"]))).user_id = doctor_user.id
        other = Patient(
            full_name="Boshqa Bemor",
            search_key=search_key("Boshqa Bemor"),
            kind=PatientKind.LEGACY,
            tags=[],
            phones=[PatientPhone(number="+998900000002", is_primary=True)],
        )
        s.add(other)
        await s.commit()
    doc = bearer(await login(client, "doc1"))
    await make_user("reg1", Role.REGISTRAR)
    reg = bearer(await login(client, "reg1"))
    day = next_monday()
    mine = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    theirs = (
        await client.post(
            "/api/appointments", json=booking(clinic, at(day, 9), doctor="d2"), headers=op
        )
    ).json()
    due = (day + timedelta(days=14)).isoformat()

    async def rec(headers: dict, **kw: str) -> tuple[int, dict]:
        body = {"patient_id": clinic["patient"], "due_date": due, **kw}
        resp = await client.post("/api/recommendations", json=body, headers=headers)
        return resp.status_code, resp.json()

    code, body = await rec(reg, appointment_id=str(uuid.uuid4()))
    assert (code, body["detail"]) == (404, "appointment_not_found")
    code, body = await rec(reg, patient_id=str(other.id), appointment_id=mine["id"])
    assert (code, body["detail"]) == (409, "appointment_patient_mismatch")
    # doctors: only for their own appointment / patient
    assert (await rec(doc, appointment_id=theirs["id"]))[0] == 403
    assert (await rec(doc, patient_id=str(other.id)))[0] == 403
    assert (await rec(doc))[0] == 201
    code, body = await rec(reg, appointment_id=theirs["id"])
    assert code == 201 and body["doctor_id"] == clinic["d2"]

    async with SessionLocal() as s:
        (await s.get(Patient, other.id)).merged_into_id = uuid.UUID(clinic["patient"])
        await s.commit()
    code, body = await rec(reg, patient_id=str(other.id))
    assert (code, body["detail"]) == (409, "patient_merged")


async def test_absences_are_audited(client: AsyncClient, clinic: dict) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    body = {"date_from": next_monday().isoformat(), "date_to": next_monday().isoformat()}

    missing = await client.post(
        f"/api/schedule/doctors/{uuid.uuid4()}/absences", json=body, headers=sup
    )
    assert missing.status_code == 404
    added = await client.post(
        f"/api/schedule/doctors/{clinic['d1']}/absences", json=body, headers=sup
    )
    assert added.status_code == 201
    schedule = (await client.get(f"/api/schedule/doctors/{clinic['d1']}", headers=sup)).json()
    assert [a["id"] for a in schedule["absences"]] == [added.json()["id"]]

    url = f"/api/schedule/absences/{added.json()['id']}"
    assert (await client.delete(url, headers=sup)).status_code == 204
    assert (await client.delete(url, headers=sup)).status_code == 404

    async with SessionLocal() as s:
        actions = list(
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_id == clinic["d1"]))
        )
    assert sorted(actions) == ["schedule.absence_add", "schedule.absence_delete"]


async def test_reschedule_keeps_the_doctor_even_if_the_catalog_changed(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    day = next_monday()
    appt = (
        await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    ).json()
    # later the site sync links the service to another doctor only
    async with SessionLocal() as s:
        s.add(
            DoctorService(
                doctor_id=uuid.UUID(clinic["d2"]), service_id=uuid.UUID(clinic["consult"])
            )
        )
        await s.commit()

    url = f"/api/appointments/{appt['id']}/reschedule"
    moved = await client.post(url, json={"starts_at": at(day, 10)}, headers=op)
    assert moved.status_code == 200, moved.text  # same doctor: what was agreed stands
    # but a new booking with that doctor follows the catalog
    fresh = await client.post("/api/appointments", json=booking(clinic, at(day, 11)), headers=op)
    assert fresh.status_code == 409 and fresh.json()["detail"] == "doctor_not_eligible"
