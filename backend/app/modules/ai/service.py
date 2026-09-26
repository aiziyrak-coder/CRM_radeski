"""AI analysis of recorded calls (TZ 4.8.1): stereo -> STT per speaker -> LLM -> call_analyses."""

import asyncio
import logging
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import emit
from app.integrations import openai_client
from app.integrations.llm import LlmError, get_llm
from app.integrations.stt import Segment, get_transcriber
from app.modules.ai.models import AnalysisStatus, CallAnalysis, QaCriterion, ReviewStatus
from app.modules.ai.prompts import (
    DEFAULT_CRITERIA,
    PROMPT_VERSION,
    RED_FLAGS,
    AnalysisOut,
    system_prompt,
    user_prompt,
)
from app.modules.patients.models import Patient
from app.modules.scripts.models import Script
from app.modules.tasks.models import Task
from app.modules.telephony import service as telephony
from app.modules.telephony.models import Call, CallDirection, RecordingStatus

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
# an in-progress analysis older than this was interrupted: well above the slowest run
# (STT chunks + flex LLM with its timeout/retries), so a slow run is never started twice
STUCK_AFTER = timedelta(minutes=90)


# --- criteria ---------------------------------------------------------------------------------


async def seed_criteria(session: AsyncSession) -> int:
    if await session.scalar(select(QaCriterion.id).limit(1)):
        return 0
    for i, (code, name_uz, name_ru, description, weight) in enumerate(DEFAULT_CRITERIA):
        session.add(
            QaCriterion(
                code=code, name_uz=name_uz, name_ru=name_ru, description=description,
                weight=weight, active=True, sort_order=i,
            )
        )  # fmt: skip
    await session.flush()
    return len(DEFAULT_CRITERIA)


async def active_criteria(session: AsyncSession) -> list[QaCriterion]:
    await seed_criteria(session)
    return list(
        await session.scalars(
            select(QaCriterion).where(QaCriterion.active).order_by(QaCriterion.sort_order)
        )
    )


def score(results: list[dict[str, Any]], weights: dict[str, int]) -> int | None:
    """Weighted share of the applicable criteria that were met (0-100); computed here, not by
    the model, so the scale stays stable when criteria or weights change."""
    applicable = [r for r in results if r.get("passed") is not None and r["code"] in weights]
    total = sum(weights[r["code"]] for r in applicable)
    if not total:
        return None
    return round(100 * sum(weights[r["code"]] for r in applicable if r["passed"]) / total)


# --- pipeline ---------------------------------------------------------------------------------


# speech detection: quieter than this for longer than SILENCE_MIN seconds counts as a pause
SILENCE_DB = -35
SILENCE_MIN = 0.6
MERGE_GAP = 1.2  # pauses shorter than this stay inside one STT chunk
MAX_CHUNK = 30.0  # seconds; keeps timestamps useful for "listen to this moment"
MIN_SPEECH = 0.4  # coughs and clicks aren't worth a request
PAD = 0.3
STT_CONCURRENCY = 4

Chunk = tuple[float, float, Path]  # start, end (seconds in the original call), audio file
_SILENCE = re.compile(r"silence_(start|end): (-?[\d.]+)")
_DURATION = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", *args],
        check=True, capture_output=True, text=True, timeout=300,
    )  # fmt: skip


def speech_intervals(stderr: str) -> list[tuple[float, float]]:
    """Speech = everything silencedetect didn't mark as silence (ffmpeg log -> intervals)."""
    if not (m := _DURATION.search(stderr)):
        return []
    duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    speech: list[tuple[float, float]] = []
    cursor: float | None = 0.0  # where the current stretch of speech began; None while silent
    for kind, value in _SILENCE.findall(stderr):
        t = max(0.0, min(float(value), duration))
        if kind == "start":
            if cursor is not None:
                speech.append((cursor, t))
            cursor = None
        else:
            cursor = t
    if cursor is not None:
        speech.append((cursor, duration))
    return [(a, b) for a, b in speech if b - a >= MIN_SPEECH]


def plan_chunks(speech: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Group speech into STT chunks: close pauses are kept, long silences are cut out."""
    chunks: list[list[float]] = []
    for a, b in speech:
        a, b = max(0.0, a - PAD), min(duration or b + PAD, b + PAD)
        if chunks and a - chunks[-1][1] < MERGE_GAP and b - chunks[-1][0] <= MAX_CHUNK:
            chunks[-1][1] = b
            continue
        while b - a > MAX_CHUNK:  # one long monologue: split it evenly
            chunks.append([a, a + MAX_CHUNK])
            a += MAX_CHUNK
        chunks.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in chunks]


def split_channels(stereo: Path, workdir: Path) -> dict[str, list[Chunk]]:
    """Left = operator, right = patient (see telephony.convert_recording). Only the parts with
    speech are sent to STT: each side is silent while the other talks, so this roughly halves the
    audio minutes that are paid for."""
    out: dict[str, list[Chunk]] = {}
    for ch, pan in (("operator", "c0"), ("patient", "c1")):
        mono = workdir / f"{ch}.wav"
        _ffmpeg(
            "-loglevel",
            "error",
            "-i",
            str(stereo),
            "-af",
            f"pan=mono|c0={pan}",
            "-ar",
            "16000",
            str(mono),
        )
        probe = _ffmpeg(
            "-i", str(mono), "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}",
            "-f", "null", "-",
        )  # fmt: skip
        dur = _DURATION.search(probe.stderr)
        duration = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else 0.0
        out[ch] = []
        for i, (a, b) in enumerate(plan_chunks(speech_intervals(probe.stderr), duration)):
            piece = workdir / f"{ch}-{i:03d}.mp3"
            _ffmpeg(
                "-loglevel", "error", "-ss", f"{a}", "-to", f"{b}", "-i", str(mono),
                "-c:a", "libmp3lame", "-b:a", "32k", str(piece),
            )  # fmt: skip
            out[ch].append((a, b, piece))
    return out


async def transcribe_call(path: Path) -> tuple[str, list[dict[str, Any]]]:
    stt = get_transcriber()
    limit = asyncio.Semaphore(STT_CONCURRENCY)

    async def one(ch: str, start: float, end: float, audio: Path) -> list[dict[str, Any]]:
        async with limit:
            segments = await stt.transcribe(audio)
        if len(segments) == 1 and segments[0].start == 0:  # plain-text models: the whole chunk
            segments = [Segment(0.0, end - start, segments[0].text)]
        return [
            {
                "ch": ch,
                "start": round(start + s.start, 1),
                "end": round(start + s.end, 1),
                "text": s.text,
            }
            for s in segments
        ]

    with tempfile.TemporaryDirectory() as tmp:
        chunks = await asyncio.to_thread(split_channels, path, Path(tmp))
        parts = await asyncio.gather(
            *(one(ch, a, b, f) for ch, items in chunks.items() for a, b, f in items)
        )
    seconds = sum(b - a for items in chunks.values() for a, b, _ in items)
    await openai_client.add_spend(openai_client.stt_cost(stt.name, seconds))
    merged = [s for part in parts for s in part]
    merged.sort(key=lambda s: (s["start"], s["ch"] != "operator"))
    return stt.name, merged


async def _context(session: AsyncSession, call: Call) -> list[str]:
    lines = [
        "inbound call (the patient called the clinic)"
        if call.direction is CallDirection.IN
        else "outbound call (the operator called the patient)",
        f"talk time: {call.talk_seconds or 0} s",
    ]
    if call.task_id and (task := await session.get(Task, call.task_id)):
        lines.append(f"reason for the call: task '{task.type.value}', script '{task.script_code}'")
    if call.patient_id and (patient := await session.get(Patient, call.patient_id)):
        lines.append(f"caller is a {patient.kind.value} patient, prefers {patient.language.value}")
    elif call.lead_id:
        lines.append("caller is a new inquiry (not a patient yet)")
    return lines


async def _scripts(session: AsyncSession, call: Call) -> list[tuple[str, str, str | None]]:
    """All script titles, but the full text only of the scripts this call should follow (the
    task's script, or the inbound one, plus the closing): most of the prompt was scripts, and
    input tokens are what an analysis costs."""
    focus = {"closing"}
    task = await session.get(Task, call.task_id) if call.task_id else None
    if task and task.script_code:
        focus.add(task.script_code)
    if call.direction is CallDirection.IN or not (task and task.script_code):
        focus.add("incoming")
    rows = await session.scalars(
        select(Script).where(Script.language == "uz").order_by(Script.sort_order, Script.code)
    )
    return [(s.code, s.title, s.body if s.code in focus else None) for s in rows]


def _clean(out: AnalysisOut, criteria: list[QaCriterion], script_codes: set[str]) -> dict:
    codes = {c.code for c in criteria}
    seen: dict[str, dict] = {}
    for r in out.criteria:
        if r.code in codes and r.code not in seen:
            seen[r.code] = {"code": r.code, "passed": r.passed, "comment": r.comment}
    results = [seen.get(c.code, {"code": c.code, "passed": None, "comment": ""}) for c in criteria]
    violations = [
        v.model_dump()
        for v in out.violations
        if v.criterion in codes and seen.get(v.criterion, {}).get("passed") is False
    ]
    flags = [f.model_dump() for f in out.red_flags if f.code in RED_FLAGS]
    return {
        "conversation_type": out.conversation_type
        if out.conversation_type in script_codes
        else None,
        "language": out.language,
        "criteria": results,
        "violations": violations,
        "red_flags": flags,
        "has_red_flags": bool(flags),
        "score": score(results, {c.code: c.weight for c in criteria}),
        "summary": out.summary.strip(),
        "suggested_outcome": out.outcome.value if out.outcome else None,
        "suggested_reason": out.reason.value if out.reason else None,
        "extracted": out.extracted.model_dump(),
        "questions": [q.strip() for q in out.questions if q.strip()][:10],
        "objections": [o.strip() for o in out.objections if o.strip()][:10],
    }


async def _claim(session: AsyncSession, call: Call) -> CallAnalysis | None:
    """Lock the call's analysis row so two workers never pay OpenAI for the same call."""
    await session.execute(
        pg_insert(CallAnalysis)
        .values(id=uuid.uuid4(), call_id=call.id, status=AnalysisStatus.PENDING, attempts=0)
        .on_conflict_do_nothing(index_elements=[CallAnalysis.call_id])
    )
    return await session.scalar(
        select(CallAnalysis)
        .where(CallAnalysis.call_id == call.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def analyze_call(session: AsyncSession, call_id: uuid.UUID) -> AnalysisStatus | None:
    """Idempotent: a call that's already analysed (or skipped, or being analysed by another
    worker) is left alone. The claim is committed before anything is sent to OpenAI."""
    if not openai_client.enabled():
        return None
    call = await session.get(Call, call_id)
    if call is None or call.recording_status is not RecordingStatus.READY or not call.recording:
        return None
    analysis = await _claim(session, call)
    if analysis is None:  # another worker holds it right now
        return None
    if analysis.status in (AnalysisStatus.READY, AnalysisStatus.SKIPPED):
        return analysis.status
    busy = (AnalysisStatus.TRANSCRIBING, AnalysisStatus.ANALYZING)
    if analysis.status in busy and analysis.updated_at > datetime.now(UTC) - STUCK_AFTER:
        return analysis.status
    settings = get_settings()
    if (call.talk_seconds or 0) < settings.ai_min_talk_seconds:
        analysis.status, analysis.error = AnalysisStatus.SKIPPED, "too_short"
        await session.flush()
        return analysis.status
    if analysis.attempts >= MAX_ATTEMPTS:
        return analysis.status
    try:
        await openai_client.ensure_budget()
    except openai_client.AiDisabledError as exc:  # today's budget is used up: try again tomorrow
        analysis.status, analysis.error = AnalysisStatus.PENDING, str(exc)
        await session.commit()
        return analysis.status

    analysis.attempts += 1
    analysis.status = (
        AnalysisStatus.ANALYZING if analysis.transcript else AnalysisStatus.TRANSCRIBING
    )
    await session.commit()  # the claim: other workers now see it as in progress
    analysis.error = None
    try:
        if not analysis.transcript:
            path = telephony.recordings_dir() / call.recording
            analysis.stt_model, analysis.transcript = await transcribe_call(path)
        if not analysis.transcript:
            analysis.status, analysis.error = AnalysisStatus.SKIPPED, "no_speech"
            await session.flush()
            return analysis.status
        analysis.status = AnalysisStatus.ANALYZING
        criteria = await active_criteria(session)
        scripts = await _scripts(session, call)
        llm = get_llm()
        out = await llm.parse(
            system=system_prompt([(c.code, c.name_uz, c.description) for c in criteria], scripts),
            user=user_prompt(await _context(session, call), analysis.transcript),
            schema=AnalysisOut,
            cache_key=f"call-analysis-{PROMPT_VERSION}",
        )
        for field, value in _clean(out, criteria, {code for code, _, _ in scripts}).items():
            setattr(analysis, field, value)
        analysis.llm_model, analysis.prompt_version = llm.name, PROMPT_VERSION
        analysis.status = AnalysisStatus.READY
    except (LlmError, openai_client.AiDisabledError, subprocess.SubprocessError, OSError) as exc:
        log.warning("analysis of call %s failed: %s", call.id, exc)
        analysis.status, analysis.error = AnalysisStatus.FAILED, str(exc)[:2000]
    except Exception as exc:  # the OpenAI SDK raises many types; never lose the call itself
        log.exception("analysis of call %s failed", call.id)
        analysis.status, analysis.error = AnalysisStatus.FAILED, repr(exc)[:2000]
    await session.flush()
    if analysis.status is AnalysisStatus.READY:
        await emit(session, "ai.analysis_ready", analysis=analysis, call=call)
    return analysis.status


async def pending_calls(session: AsyncSession, limit: int = 50) -> list[uuid.UUID]:
    """Calls to (re)analyse: never started, failed with attempts left, or stuck mid-way."""
    now = datetime.now(UTC)
    week = now - timedelta(days=7)
    stuck = now - STUCK_AFTER
    new = select(Call.id).where(
        Call.recording_status == RecordingStatus.READY,
        Call.ended_at > week,
        ~select(CallAnalysis.id).where(CallAnalysis.call_id == Call.id).exists(),
    )
    retry = (
        select(CallAnalysis.call_id)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(
            Call.ended_at > week,
            CallAnalysis.attempts < MAX_ATTEMPTS,
            (CallAnalysis.status == AnalysisStatus.FAILED)
            | (
                CallAnalysis.status.in_(
                    (AnalysisStatus.PENDING, AnalysisStatus.TRANSCRIBING, AnalysisStatus.ANALYZING)
                )
                & (CallAnalysis.updated_at < stuck)
            ),
        )
    )
    ids = list(await session.scalars(new.limit(limit))) + list(
        await session.scalars(retry.limit(limit))
    )
    return ids[:limit]


# --- operator review (plan 4.4) ---------------------------------------------------------------


async def suggestions_for_tasks(
    session: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """The newest un-reviewed analysis of a call made from each task."""
    if not task_ids:
        return {}
    rows = await session.execute(
        select(Call.task_id, CallAnalysis)
        .join(CallAnalysis, CallAnalysis.call_id == Call.id)
        .where(
            Call.task_id.in_(task_ids),
            CallAnalysis.status == AnalysisStatus.READY,
            CallAnalysis.review.is_(None),
        )
        .order_by(Call.started_at)
    )
    return {
        task_id: {
            "analysis_id": a.id,
            "call_id": a.call_id,
            "outcome": a.suggested_outcome,
            "reason": a.suggested_reason,
            "summary": a.summary,
            "next_step": (a.extracted or {}).get("next_step"),
        }
        for task_id, a in rows
    }


async def record_review(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    *,
    outcome: str,
    reason: str | None,
    user_id: uuid.UUID,
) -> CallAnalysis | None:
    analysis = await session.get(CallAnalysis, analysis_id)
    if analysis is None or analysis.review is not None:
        return analysis
    corrections = {}
    if analysis.suggested_outcome != outcome:
        corrections["outcome"] = {"ai": analysis.suggested_outcome, "operator": outcome}
    if (analysis.suggested_reason or None) != (reason or None):
        corrections["reason"] = {"ai": analysis.suggested_reason, "operator": reason}
    analysis.review = ReviewStatus.CORRECTED if corrections else ReviewStatus.CONFIRMED
    analysis.corrections = corrections or None
    analysis.reviewed_by, analysis.reviewed_at = user_id, datetime.now(UTC)
    await session.flush()
    return analysis
