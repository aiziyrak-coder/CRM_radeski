"""Phase 3: PBX call events, missed-call tasks, softphone credentials, recordings."""

import asyncio
import hashlib
import hmac
import shutil
import struct
import time as systime
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.leads.models import Lead
from app.modules.tasks.models import Task, TaskStatus, TaskType
from app.modules.telephony import router as telephony_router
from app.modules.telephony import service
from app.modules.telephony.models import Call
from app.modules.users.models import Role, User
from tests.conftest import bearer, login, make_user

SECRET = "pbx-test-secret"
PATIENT_PHONE = "900000001"  # the `clinic` fixture's patient


@pytest.fixture(autouse=True)
def pbx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    settings = get_settings()
    monkeypatch.setattr(settings, "pbx_api_secret", SECRET)
    monkeypatch.setattr(settings, "pbx_sip_secret", "sip-test-secret")
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    queued: list[str] = []
    monkeypatch.setattr(telephony_router, "_enqueue_recording", lambda cid: queued.append(str(cid)))
    return queued


async def event(client: AsyncClient, secret: str = SECRET, **fields: object) -> dict:
    now = int(systime.time())
    body = {"started": now - 60, "ended": now, **fields}
    resp = await client.post(
        "/api/telephony/events",
        content=urlencode(body),
        headers={"X-PBX-Secret": secret},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def open_tasks(type_: TaskType) -> list[Task]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(select(Task).where(Task.type == type_, Task.status == TaskStatus.OPEN))
        )


async def get_call(pbx_id: str) -> Call:
    async with SessionLocal() as s:
        return (await s.scalars(select(Call).where(Call.pbx_id == pbx_id))).one()


async def test_events_need_the_shared_secret(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/telephony/events",
        content="kind=end&call_id=1.1",
        headers={"X-PBX-Secret": "wrong"},
    )
    assert resp.status_code == 401
    assert (await client.post("/api/telephony/events", content="kind=end")).status_code == 401
    # an id that could escape the recordings folder is ignored
    assert (await event(client, kind="end", call_id="../../etc/passwd")) == {"ok": False}


async def test_missed_call_from_patient_becomes_one_callback_task(
    client: AsyncClient, clinic: dict
) -> None:
    await event(client, kind="ring", call_id="100.1", caller=PATIENT_PHONE)
    ringing = await get_call("100.1")
    assert ringing.status == "ringing" and str(ringing.patient_id) == clinic["patient"]

    await event(
        client, kind="end", direction="in", call_id="100.1", caller=PATIENT_PHONE,
        status="missed", wait="45", callback="1",
    )  # fmt: skip
    call = await get_call("100.1")
    assert call.status == "missed" and call.wait_seconds == 45 and call.callback_requested
    [task] = await open_tasks(TaskType.MISSED_CALL)
    assert str(task.patient_id) == clinic["patient"] and "1 ni bosib" in (task.note or "")

    # calling again the same day doesn't pile up tasks
    await event(
        client, kind="end", direction="in", call_id="100.2", caller=f"+998{PATIENT_PHONE}",
        status="abandoned",
    )  # fmt: skip
    assert len(await open_tasks(TaskType.MISSED_CALL)) == 1

    # getting through closes it
    await event(
        client, kind="end", direction="in", call_id="100.3", caller=PATIENT_PHONE,
        status="answered", agent="101", talk="120",
    )  # fmt: skip
    assert await open_tasks(TaskType.MISSED_CALL) == []
    answered = await get_call("100.3")
    assert answered.talk_seconds == 120 and answered.recording_status == "pending"


async def test_missed_call_from_unknown_number_opens_an_inquiry(client: AsyncClient) -> None:
    await event(
        client, kind="end", direction="in", call_id="200.1", caller="998935550011",
        status="after_hours",
    )  # fmt: skip
    async with SessionLocal() as s:
        lead = (await s.scalars(select(Lead))).one()
    assert lead.channel == "missed_call" and lead.phone == "+998935550011"
    [task] = await open_tasks(TaskType.NEW_LEAD)
    assert task.lead_id == lead.id
    assert (await get_call("200.1")).lead_id == lead.id

    # the same number calling again becomes a callback on that inquiry, not a second lead
    await event(
        client, kind="end", direction="in", call_id="200.2", caller="935550011", status="missed"
    )
    async with SessionLocal() as s:
        assert len(list(await s.scalars(select(Lead)))) == 1
    [missed] = await open_tasks(TaskType.MISSED_CALL)
    assert missed.lead_id == lead.id


async def test_outbound_call_from_a_task_is_linked(
    client: AsyncClient, clinic: dict, pbx: list[str]
) -> None:
    await make_user("op1", Role.OPERATOR)
    async with SessionLocal() as s:
        user = (await s.scalars(select(User).where(User.username == "op1"))).one()
        user.sip_extension = "101"
        await s.commit()
    op = bearer(await login(client, "op1"))
    await client.post(
        "/api/tasks",
        json={"patient_id": clinic["patient"], "due_at": datetime.now(UTC).isoformat()},
        headers=op,
    )
    [task] = await open_tasks(TaskType.CALLBACK)

    await event(
        client, kind="end", direction="out", call_id="300.1", caller=PATIENT_PHONE,
        status="ANSWER", agent="101", talk="95", task=str(task.id),
    )  # fmt: skip
    call = await get_call("300.1")
    assert call.status == "answered" and call.task_id == task.id
    assert str(call.patient_id) == clinic["patient"] and call.user_id == user.id
    assert pbx == [str(call.id)]  # recording queued for conversion

    await event(
        client, kind="end", direction="out", call_id="300.2", caller="901112233",
        status="CHANUNAVAIL", agent="101",
    )  # fmt: skip
    failed = await get_call("300.2")
    assert (
        failed.status == "failed" and failed.talk_seconds == 0 and failed.recording_status is None
    )

    log = {c["status"]: c for c in (await client.get("/api/telephony/calls", headers=op)).json()}
    assert set(log) == {"failed", "answered"}
    assert log["answered"]["patient_name"] == "Sinov Bemor" and log["answered"]["user_name"]
    mine = (await client.get("/api/telephony/calls", params={"who": "mine"}, headers=op)).json()
    assert len(mine) == 2
    by_patient = (
        await client.get(
            "/api/telephony/calls", params={"patient_id": clinic["patient"]}, headers=op
        )
    ).json()
    assert [c["id"] for c in by_patient] == [str(call.id)]


async def test_softphone_credentials_only_for_own_extension(client: AsyncClient) -> None:
    await make_user("admin1", Role.ADMIN)
    admin = bearer(await login(client, "admin1"))
    await make_user("op1", Role.OPERATOR)
    await make_user("op2", Role.OPERATOR)
    op = bearer(await login(client, "op1"))
    assert (await client.get("/api/telephony/me", headers=op)).json() == {
        "enabled": False, "extension": None, "password": None,
    }  # fmt: skip

    users = {u["username"]: u["id"] for u in (await client.get("/api/users", headers=admin)).json()}
    resp = await client.patch(
        f"/api/users/{users['op1']}", json={"sip_extension": "102"}, headers=admin
    )
    assert resp.status_code == 200 and resp.json()["sip_extension"] == "102"
    taken = await client.patch(
        f"/api/users/{users['op2']}", json={"sip_extension": "102"}, headers=admin
    )
    assert taken.status_code == 409 and taken.json()["detail"] == "extension_taken"

    me = (await client.get("/api/telephony/me", headers=op)).json()
    expected = hmac.new(b"sip-test-secret", b"ext:102", hashlib.sha256).hexdigest()[:32]
    assert me == {"enabled": True, "extension": "102", "password": expected}

    # an extension that the PBX doesn't define gives no credentials
    await client.patch(f"/api/users/{users['op1']}", json={"sip_extension": "999"}, headers=admin)
    assert (await client.get("/api/telephony/me", headers=op)).json()["enabled"] is False


async def test_lookup_for_incoming_popup(client: AsyncClient, clinic: dict, op: dict) -> None:
    found = (
        await client.get("/api/telephony/lookup", params={"phone": "+998900000001"}, headers=op)
    ).json()
    assert found["patient"]["full_name"] == "Sinov Bemor" and found["phone"] == "+998900000001"
    unknown = (
        await client.get("/api/telephony/lookup", params={"phone": "933334455"}, headers=op)
    ).json()
    assert unknown["patient"] is None and unknown["lead"] is None
    assert (await client.get("/api/telephony/lookup", params={"phone": "12"}, headers=op)).json()[
        "phone"
    ] is None


def _wav(path: Path, seconds: float, freq: int) -> None:
    import math

    rate = 8000
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(rate * seconds))
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


async def test_recording_access(client: AsyncClient, clinic: dict, tmp_path: Path) -> None:
    await make_user("op1", Role.OPERATOR)
    await make_user("op2", Role.OPERATOR)
    await make_user("sup1", Role.SUPERVISOR)
    async with SessionLocal() as s:
        user = (await s.scalars(select(User).where(User.username == "op1"))).one()
        user.sip_extension = "101"
        await s.commit()
    await event(
        client, kind="end", direction="in", call_id="400.1", caller=PATIENT_PHONE,
        status="answered", agent="101", talk="30",
    )  # fmt: skip
    call = await get_call("400.1")
    url = f"/api/telephony/calls/{call.id}/recording"
    op1 = bearer(await login(client, "op1"))
    assert (await client.get(url, headers=op1)).status_code == 404  # not converted yet

    (tmp_path / "400.1.mp3").write_bytes(b"ID3fake")
    async with SessionLocal() as s:
        stored = await s.get(Call, call.id)
        stored.recording, stored.recording_status = "400.1.mp3", "ready"
        await s.commit()
    assert (await client.get(url, headers=op1)).status_code == 200
    op2 = bearer(await login(client, "op2"))
    assert (await client.get(url, headers=op2)).status_code == 403
    sup = bearer(await login(client, "sup1"))
    resp = await client.get(url, headers=sup)
    assert resp.status_code == 200 and resp.headers["content-type"] == "audio/mpeg"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_convert_recording_to_stereo(tmp_path: Path) -> None:
    _wav(tmp_path / "500.1-out.wav", 1.0, 440)  # operator
    _wav(tmp_path / "500.1-in.wav", 1.5, 880)  # patient talks a bit longer
    (tmp_path / "500.1-mix.wav").write_bytes(b"x")
    assert service.convert_recording("500.1") == "500.1.mp3"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["500.1.mp3"]
    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=channels:format=duration",
         "-of", "default=nw=1", str(tmp_path / "500.1.mp3")],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "channels=2" in probe
    duration = float(probe.split("duration=")[1].split()[0])
    assert 1.4 < duration < 1.7
    assert service.convert_recording("missing") is None


async def test_failed_conversions_are_retried(client: AsyncClient, tmp_path: Path) -> None:
    await event(
        client, kind="end", direction="in", call_id="600.1", caller=PATIENT_PHONE,
        status="answered", agent="101", talk="10",
    )  # fmt: skip
    call = await get_call("600.1")
    async with SessionLocal() as s:
        stored = await s.get(Call, call.id)
        stored.recording_status = "failed"
        stored.ended_at = datetime.now(UTC) - timedelta(minutes=10)
        await s.commit()
    (tmp_path / "600.1-in.wav").write_bytes(b"")  # nothing usable -> "missing", not a loop
    async with SessionLocal() as s:
        assert await service.retry_recordings(s) == 1
        await s.commit()
    assert (await get_call("600.1")).recording_status == "missing"
    async with SessionLocal() as s:
        assert await service.retry_recordings(s) == 0


async def test_reports_count_calls(client: AsyncClient, clinic: dict) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    empty = (await client.get("/api/reports/daily", headers=sup)).json()
    assert empty["inbound_calls"] is None  # PBX never reported anything yet

    for i, status in enumerate(["answered", "missed", "abandoned"]):
        await event(
            client, kind="end", direction="in", call_id=f"700.{i}", caller=PATIENT_PHONE,
            status=status, agent="101" if status == "answered" else "", wait="20",
            talk="120" if status == "answered" else "0", callback="1" if i == 1 else "0",
        )  # fmt: skip
    await event(
        client, kind="end", direction="out", call_id="700.9", caller=PATIENT_PHONE,
        status="answer", agent="101", talk="60",
    )  # fmt: skip
    day = (await client.get("/api/reports/daily", headers=sup)).json()
    assert day["inbound_calls"] == 3 and day["inbound_answered"] == 1
    assert day["inbound_missed"] == 2 and day["inbound_answer_rate"] == 33.3
    assert day["callbacks_requested"] == 1 and day["avg_wait_sec"] == 20
    assert day["outbound_calls"] == 1 and day["talk_minutes"] == 3
    today = clinic_time.today().isoformat()
    kpi = (
        await client.get("/api/reports/kpi", params={"from": today, "to": today}, headers=sup)
    ).json()
    assert kpi["inbound_calls"] == 3
    xlsx = await client.get(
        "/api/reports/kpi.xlsx", params={"from": today, "to": today}, headers=sup
    )
    assert xlsx.status_code == 200


# --- lost reports, odd caller ids, races --------------------------------------------------------


async def test_call_without_hangup_report_is_closed_as_missed(client: AsyncClient) -> None:
    long_ago = int(systime.time()) - 3 * 3600
    await event(client, kind="ring", call_id="800.1", caller="998935550077", started=long_ago)
    await event(client, kind="ring", call_id="800.2", caller="998935550078")  # still in the queue
    async with SessionLocal() as s:
        assert await service.close_stale_calls(s) == 1
        await s.commit()
    stale = await get_call("800.1")
    assert stale.status == "missed" and stale.ended_at is None
    assert (await get_call("800.2")).status == "ringing"
    async with SessionLocal() as s:  # the missed-call rule ran: the number is called back
        lead = (await s.scalars(select(Lead))).one()
    assert lead.phone == "+998935550077" and (await get_call("800.1")).lead_id == lead.id
    async with SessionLocal() as s:
        assert await service.close_stale_calls(s) == 0

    # the real report arrives after all (the CRM was down): it wins over the guess
    await event(
        client, kind="end", direction="in", call_id="800.1", caller="998935550077",
        status="answered", agent="101", talk="30", started=long_ago,
    )  # fmt: skip
    call = await get_call("800.1")
    assert call.status == "answered" and call.ended_at is not None and call.talk_seconds == 30
    # ...but a report repeated after that is still ignored
    await event(client, kind="end", direction="in", call_id="800.1", status="missed")
    assert (await get_call("800.1")).status == "answered"


@pytest.mark.parametrize("caller", ["anonymous", "+4915112345678", "1050", ""])
async def test_non_uzbek_caller_ids_never_reach_inquiries(client: AsyncClient, caller: str) -> None:
    await event(client, kind="ring", call_id="810.1", caller=caller)
    await event(client, kind="end", direction="in", call_id="810.1", caller=caller, status="missed")
    call = await get_call("810.1")
    assert call.status == "missed" and call.phone is None
    assert call.caller_raw == (caller or None)
    async with SessionLocal() as s:
        assert not list(await s.scalars(select(Lead)))
    calls = (await client.get("/api/telephony/calls", headers=await _viewer(client))).json()
    assert calls[0]["phone"] is None and calls[0]["caller_raw"] == (caller or None)


async def _viewer(client: AsyncClient) -> dict:
    await make_user("sup9", Role.SUPERVISOR)
    return bearer(await login(client, "sup9"))


async def test_ring_and_end_arriving_together_make_one_call(clinic: dict) -> None:
    now = int(systime.time())
    ring = {"kind": "ring", "call_id": "820.1", "caller": PATIENT_PHONE, "started": str(now)}
    end = {**ring, "kind": "end", "direction": "in", "status": "missed", "ended": str(now)}

    async def post(data: dict) -> None:
        async with SessionLocal() as s:
            await service.record_event(s, data)
            await s.commit()

    await asyncio.gather(post(ring), post(end), post(end))
    call = await get_call("820.1")
    assert call.status == "missed" and str(call.patient_id) == clinic["patient"]
    assert len(await open_tasks(TaskType.MISSED_CALL)) == 1


async def test_recording_conversion_is_claimed(client: AsyncClient, tmp_path: Path) -> None:
    await event(
        client, kind="end", direction="in", call_id="830.1", caller=PATIENT_PHONE,
        status="answered", agent="101", talk="10",
    )  # fmt: skip
    call = await get_call("830.1")
    async with SessionLocal() as busy:  # another worker is converting it right now
        await busy.scalar(select(Call).where(Call.id == call.id).with_for_update())
        async with SessionLocal() as s:
            assert await service.process_recording(s, call.id) is None
        await busy.rollback()

    # converted earlier, but the worker died before storing the result: the MP3 is reused
    (tmp_path / "830.1.mp3").write_bytes(b"ID3fake")
    assert service.convert_recording("830.1") == "830.1.mp3"
    async with SessionLocal() as s:
        assert await service.process_recording(s, call.id) == "ready"
        await s.commit()
    stored = await get_call("830.1")
    assert stored.recording == "830.1.mp3" and stored.recording_status == "ready"
