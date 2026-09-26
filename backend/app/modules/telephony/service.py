"""Call log fed by the Asterisk dialplan (telephony/asterisk/extensions.conf)."""

import hashlib
import hmac
import logging
import re
import subprocess
import uuid
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import emit
from app.core.text import InvalidPhoneError, normalize_uz_phone
from app.modules.leads.models import OPEN_STAGES, Lead
from app.modules.leads.service import find_patient_by_phone
from app.modules.patients import service as patients_service
from app.modules.tasks.models import Task
from app.modules.telephony.models import (
    Call,
    CallDirection,
    CallStatus,
    RecordingStatus,
)
from app.modules.users.models import User

log = logging.getLogger(__name__)
PBX_ID = re.compile(r"[0-9A-Za-z_.-]{1,64}")

INBOUND_STATUS = {
    "answered": CallStatus.ANSWERED,
    "missed": CallStatus.MISSED,
    "abandoned": CallStatus.ABANDONED,
    "after_hours": CallStatus.AFTER_HOURS,
}
# Asterisk DIALSTATUS (lower-cased) for calls the operators make
OUTBOUND_STATUS = {
    "answer": CallStatus.ANSWERED,
    "noanswer": CallStatus.NO_ANSWER,
    "cancel": CallStatus.NO_ANSWER,
    "busy": CallStatus.BUSY,
}


def extensions() -> list[str]:
    return get_settings().pbx_extensions.split()


def sip_password(extension: str) -> str:
    """Same derivation as telephony/entrypoint.sh."""
    secret = get_settings().pbx_sip_secret.encode()
    return hmac.new(secret, f"ext:{extension}".encode(), hashlib.sha256).hexdigest()[:32]


def valid_pbx_secret(value: str | None) -> bool:
    secret = get_settings().pbx_api_secret
    return bool(secret and value and hmac.compare_digest(secret, value))


def _int(value: str | None) -> int | None:
    try:
        return max(0, int(float(value))) if value not in (None, "") else None
    except ValueError:
        return None


def _epoch(value: str | None) -> datetime | None:
    seconds = _int(value)
    return datetime.fromtimestamp(seconds, UTC) if seconds else None


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def e164(raw: str | None) -> str | None:
    try:
        return normalize_uz_phone(raw) if raw else None
    except InvalidPhoneError:
        return None


def phone_of(raw: str | None) -> str | None:
    """E.164 for Uzbek numbers; anything else (short codes, foreign) is kept as reported."""
    return e164(raw) or (raw[:32] if raw else None)


async def _link(session: AsyncSession, call: Call) -> None:
    """Attach the patient (or the open inquiry) the number belongs to."""
    if call.patient_id or not call.phone:
        return
    patient = await find_patient_by_phone(session, call.phone)
    if patient:
        call.patient_id = patient.id
        return
    lead_id = await session.scalar(
        select(Lead.id)
        .where(Lead.phone == call.phone, Lead.stage.in_(OPEN_STAGES))
        .order_by(Lead.created_at.desc())
        .limit(1)
    )
    call.lead_id = lead_id


async def record_event(session: AsyncSession, data: dict[str, str]) -> Call | None:
    """`ring` opens the call row (live view); `end` completes it and triggers the task rules."""
    pbx_id = (data.get("call_id") or "").strip()[:64]
    kind = data.get("kind")
    # the id becomes a file name for the recording: accept Asterisk's UNIQUEID shape only
    if not PBX_ID.fullmatch(pbx_id) or kind not in ("ring", "end"):
        return None
    call = await session.scalar(select(Call).where(Call.pbx_id == pbx_id))
    direction = CallDirection.OUT if data.get("direction") == "out" else CallDirection.IN
    if call is None:
        call = Call(
            pbx_id=pbx_id,
            direction=direction,
            status=CallStatus.RINGING,
            phone=phone_of(data.get("caller")),
            started_at=_epoch(data.get("started")) or datetime.now(UTC),
            callback_requested=False,
        )
        session.add(call)
    if kind == "ring":
        await _link(session, call)
        await session.flush()
        return call
    if call.status is not CallStatus.RINGING:
        return call  # the same hangup reported twice

    raw_status = (data.get("status") or "").lower()
    if direction is CallDirection.IN:
        call.status = INBOUND_STATUS.get(raw_status, CallStatus.ABANDONED)
    else:
        call.status = OUTBOUND_STATUS.get(raw_status, CallStatus.FAILED)
    call.direction = direction
    call.phone = phone_of(data.get("caller")) or call.phone
    call.started_at = _epoch(data.get("started")) or call.started_at
    call.ended_at = _epoch(data.get("ended")) or datetime.now(UTC)
    call.wait_seconds = _int(data.get("wait"))
    call.talk_seconds = _int(data.get("talk")) if call.status is CallStatus.ANSWERED else 0
    call.callback_requested = data.get("callback") == "1"
    extension = (data.get("agent") or "").strip()[:10] or None
    call.extension = extension
    if extension:
        call.user_id = await session.scalar(select(User.id).where(User.sip_extension == extension))
    task_id = _uuid(data.get("task"))
    task = await session.get(Task, task_id) if task_id else None
    if task:  # called from a task card: the call belongs to that patient / inquiry
        call.task_id = task.id
        call.patient_id = call.patient_id or task.patient_id
        call.lead_id = call.lead_id or task.lead_id
    await _link(session, call)
    if call.status is CallStatus.ANSWERED:
        call.recording_status = RecordingStatus.PENDING
    await session.flush()
    await emit(session, "call.finished", call=call)
    return call


# --- recordings -------------------------------------------------------------------------------


def recordings_dir() -> Path:
    return Path(get_settings().recordings_dir)


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, OSError, EOFError):
        return 0.0


def convert_recording(pbx_id: str) -> str | None:
    """Two mono WAVs from MixMonitor -> one stereo MP3 (left = operator, right = patient).

    Keeping the speakers on separate channels lets speech-to-text transcribe each side on its
    own (phase 4). Returns the file name, or None when the call left no audio.
    """
    base = recordings_dir()
    operator, patient = base / f"{pbx_id}-out.wav", base / f"{pbx_id}-in.wav"
    parts = [p for p in (operator, patient) if p.exists() and p.stat().st_size > 44]
    if not parts:
        return None
    target = base / f"{pbx_id}.mp3"
    if len(parts) == 2:
        length = max(_duration(operator), _duration(patient))
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(operator), "-i", str(patient),
            "-filter_complex", "[0:a]apad[l];[1:a]apad[r];[l][r]amerge=inputs=2[a]",
            "-map", "[a]", "-t", f"{length:.2f}",
        ]  # fmt: skip
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(parts[0])]
    cmd += ["-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(target)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    for leftover in (operator, patient, base / f"{pbx_id}-mix.wav"):
        leftover.unlink(missing_ok=True)
    return target.name


async def process_recording(
    session: AsyncSession, call_id: uuid.UUID, *, retry: bool = False
) -> RecordingStatus | None:
    call = await session.get(Call, call_id)
    allowed = (
        (RecordingStatus.PENDING, RecordingStatus.FAILED) if retry else (RecordingStatus.PENDING,)
    )
    if call is None or call.recording_status not in allowed:
        return None
    try:
        name = convert_recording(call.pbx_id)
    except (subprocess.SubprocessError, OSError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        log.error("recording conversion failed for call %s: %s %s", call.id, exc, stderr[-500:])
        call.recording_status = RecordingStatus.FAILED
    else:
        call.recording = name
        call.recording_status = RecordingStatus.READY if name else RecordingStatus.MISSING
    await session.flush()
    return call.recording_status


async def retry_recordings(session: AsyncSession) -> int:
    """Every 30 min: conversions that failed or never ran (worker down, broker hiccup)."""
    now = datetime.now(UTC)
    ids = list(
        await session.scalars(
            select(Call.id).where(
                Call.recording_status.in_((RecordingStatus.PENDING, RecordingStatus.FAILED)),
                Call.ended_at < now - timedelta(minutes=5),
                Call.ended_at > now - timedelta(days=2),
            )
        )
    )
    for call_id in ids:
        await process_recording(session, call_id, retry=True)
    return len(ids)


async def _merge_patients(session: AsyncSession, target: uuid.UUID, source: uuid.UUID) -> None:
    await session.execute(update(Call).where(Call.patient_id == source).values(patient_id=target))


patients_service.MERGE_HOOKS.append(_merge_patients)
