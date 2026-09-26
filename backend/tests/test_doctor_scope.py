"""ARXITEKTURA 5: a doctor sees only their own patients; history views are audited."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Doctor
from app.modules.patients.models import Patient, PatientKind, PatientPhone
from app.modules.telephony.models import Call, CallDirection, CallStatus
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import at, booking, next_monday


async def _setup(client: AsyncClient, clinic: dict, op: dict) -> dict:
    """doc1 is doctor A with the fixture patient; a second patient only saw doctor B."""
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
    day = next_monday()
    mine = await client.post("/api/appointments", json=booking(clinic, at(day, 9)), headers=op)
    theirs = await client.post(
        "/api/appointments",
        json={**booking(clinic, at(day, 9), doctor="d2"), "patient_id": str(other.id)},
        headers=op,
    )
    assert mine.status_code == 201 and theirs.status_code == 201
    return {
        "doc": bearer(await login(client, "doc1")),
        "day": day.isoformat(),
        "mine": clinic["patient"],
        "other": str(other.id),
    }


async def test_doctor_day_is_only_their_own_column(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    ctx = await _setup(client, clinic, op)
    params = {"date": ctx["day"], "branch_id": clinic["branch"]}

    everyone = (await client.get("/api/appointments/day", params=params, headers=op)).json()
    assert len(everyone) == 2
    own = await client.get(
        "/api/appointments/day", params={**params, "doctor_id": clinic["d2"]}, headers=ctx["doc"]
    )
    assert own.status_code == 200
    assert [a["patient_id"] for a in own.json()] == [ctx["mine"]]

    await make_user("doc2", Role.DOCTOR)  # an account not linked to any doctor
    unlinked = bearer(await login(client, "doc2"))
    resp = await client.get("/api/appointments/day", params=params, headers=unlinked)
    assert resp.status_code == 403


async def test_doctor_sees_only_their_patients_history(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    ctx = await _setup(client, clinic, op)
    doc = ctx["doc"]

    for path in ("/api/appointments/patient/{}", "/api/recommendations/patient/{}"):
        assert (await client.get(path.format(ctx["mine"]), headers=doc)).status_code == 200
        assert (await client.get(path.format(ctx["other"]), headers=doc)).status_code == 403
        assert (await client.get(path.format(ctx["other"]), headers=op)).status_code == 200

    assert (
        await client.get(f"/api/patients/{ctx['mine']}/timeline", headers=doc)
    ).status_code == 200
    assert (
        await client.get(f"/api/patients/{ctx['other']}/timeline", headers=doc)
    ).status_code == 403


async def test_timeline_view_is_audited_and_names_the_operator(
    client: AsyncClient, clinic: dict, op: dict
) -> None:
    me = (await client.get("/api/auth/me", headers=op)).json()
    async with SessionLocal() as s:
        s.add(
            Call(
                pbx_id="test-call-1",
                direction=CallDirection.IN,
                status=CallStatus.ANSWERED,
                phone="+998900000001",
                patient_id=uuid.UUID(clinic["patient"]),
                user_id=uuid.UUID(me["id"]),
                started_at=datetime.now(UTC),
                talk_seconds=42,
            )
        )
        await s.commit()

    feed = (await client.get(f"/api/patients/{clinic['patient']}/timeline", headers=op)).json()
    [phone] = [e for e in feed if e["kind"] == "phone"]
    assert phone["user_id"] == me["id"]

    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(AuditLog.action == "patient.timeline"))
    assert log is not None and log.entity_id == clinic["patient"]
    assert str(log.user_id) == me["id"]
