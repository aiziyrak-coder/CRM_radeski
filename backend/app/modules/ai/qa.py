"""QA panel figures (plan 4.5), pre-call brief and weekly digest (plan 4.6)."""

import json
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.text import search_key
from app.integrations import openai_client
from app.integrations.llm import LlmError, get_llm
from app.modules.ai.models import AiDigest, AnalysisStatus, CallAnalysis, QaCriterion
from app.modules.ai.prompts import mask_pii
from app.modules.ai.service import active_criteria
from app.modules.patients.models import Patient, PatientCondition
from app.modules.scheduling.models import Appointment
from app.modules.tasks.models import Task, TaskAttempt, TaskStatus
from app.modules.telephony.models import Call, RecordingStatus
from app.modules.users.models import User


def _range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return clinic_time.day_bounds(date_from)[0], clinic_time.day_bounds(date_to)[1]


def _avg(scores: list[int | None]) -> int | None:
    known = [s for s in scores if s is not None]
    return round(sum(known) / len(known)) if known else None


def _rate(part: int, whole: int) -> int | None:
    return round(100 * part / whole) if whole else None


def _ready(start: datetime, end: datetime):
    return (
        select(CallAnalysis, Call)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(
            CallAnalysis.status == AnalysisStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
        )
    )


async def overview(
    session: AsyncSession, date_from: date, date_to: date, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    start, end = _range(date_from, date_to)
    # only the columns the panel needs: a year of full rows would drag every transcript along
    stmt = (
        select(
            Call.user_id,
            CallAnalysis.score,
            CallAnalysis.criteria,
            CallAnalysis.has_red_flags,
            CallAnalysis.flags_reviewed_at,
            CallAnalysis.review,
        )
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(
            CallAnalysis.status == AnalysisStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
        )
    )
    if user_id:
        stmt = stmt.where(Call.user_id == user_id)
    rows = (await session.execute(stmt)).all()
    names = dict((await session.execute(select(User.id, User.full_name))).all())
    per_user: dict[Any, list[Any]] = {}
    for row in rows:
        per_user.setdefault(row.user_id, []).append(row)
    criteria = list(await session.scalars(select(QaCriterion).order_by(QaCriterion.sort_order)))
    passed, applicable = Counter(), Counter()
    for row in rows:
        for r in row.criteria or []:
            if r.get("passed") is not None:
                applicable[r["code"]] += 1
                passed[r["code"]] += bool(r["passed"])
    return {
        "analysed": len(rows),
        "avg_score": _avg([r.score for r in rows]),
        "red_flags_open": sum(1 for r in rows if r.has_red_flags and not r.flags_reviewed_at),
        "operators": sorted(
            (
                {
                    "user_id": uid,
                    "name": names.get(uid, "—") if uid else "—",
                    "calls": len(items),
                    "avg_score": _avg([r.score for r in items]),
                    "red_flags": sum(r.has_red_flags for r in items),
                }
                for uid, items in per_user.items()
            ),
            key=lambda o: -o["calls"],
        ),
        "criteria": [
            {
                "code": c.code,
                "name_uz": c.name_uz,
                "name_ru": c.name_ru,
                "applicable": applicable[c.code],
                "pass_rate": _rate(passed[c.code], applicable[c.code]),
            }
            for c in criteria
        ],
        "reviews": dict(
            Counter(r.review.value for r in rows if r.review is not None)
        ),
    }  # fmt: skip


async def calls(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    user_id: uuid.UUID | None = None,
    flagged: bool = False,
    order: str = "recent",
    limit: int = 50,
) -> list[dict[str, Any]]:
    start, end = _range(date_from, date_to)
    stmt = (
        select(CallAnalysis, Call, Patient.full_name, User.full_name)
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(Patient, Patient.id == Call.patient_id)
        .outerjoin(User, User.id == Call.user_id)
        .where(
            CallAnalysis.status == AnalysisStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
        )
    )
    if user_id:
        stmt = stmt.where(Call.user_id == user_id)
    if flagged:
        stmt = stmt.where(CallAnalysis.has_red_flags)
    stmt = stmt.order_by(
        CallAnalysis.score.asc().nulls_last()
        if order == "worst"
        else CallAnalysis.score.desc().nulls_last()
        if order == "best"
        else Call.started_at.desc()
    ).limit(limit)
    return [
        {
            "analysis_id": a.id,
            "call_id": call.id,
            "started_at": call.started_at,
            "direction": call.direction.value,
            "talk_seconds": call.talk_seconds,
            "user_id": call.user_id,
            "user_name": user_name,
            "patient_id": call.patient_id,
            "patient_name": patient_name,
            "score": a.score,
            "conversation_type": a.conversation_type,
            "red_flags": sorted({f["code"] for f in a.red_flags or []}),
            "flags_reviewed": a.flags_reviewed_at is not None,
            "summary": a.summary,
            "review": a.review.value if a.review else None,
        }
        for a, call, patient_name, user_name in await session.execute(stmt)
    ]


# --- pre-call brief ---------------------------------------------------------------------------


class BriefOut(BaseModel):
    text: str = Field(description="3-5 short lines for the operator, in the requested language")


async def patient_facts(session: AsyncSession, patient: Patient) -> list[str]:
    facts = [
        f"patient kind: {patient.kind.value}; language: {patient.language.value}",
    ]
    if patient.birth_date:
        facts.append(f"age: {(clinic_time.today() - patient.birth_date).days // 365}")
    if patient.district:
        facts.append(f"district: {patient.district}")
    conditions = sorted(
        set(
            await session.scalars(
                select(PatientCondition.raw_text).where(PatientCondition.patient_id == patient.id)
            )
        )
    )[:5]
    if conditions:
        facts.append("diagnoses on record: " + "; ".join(conditions))
    if patient.last_visit_at:
        facts.append(f"last visit: {clinic_time.local(patient.last_visit_at).date()}")
    visits = await session.scalars(
        select(Appointment)
        .where(Appointment.patient_id == patient.id)
        .order_by(Appointment.starts_at.desc())
        .limit(3)
    )
    for a in visits:
        facts.append(
            f"appointment {clinic_time.local(a.starts_at):%Y-%m-%d %H:%M}: {a.status.value}"
        )
    summaries = await session.scalars(
        select(CallAnalysis.summary)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(Call.patient_id == patient.id, CallAnalysis.summary.is_not(None))
        .order_by(Call.started_at.desc())
        .limit(3)
    )
    facts += [f"earlier call: {s}" for s in summaries]
    attempts = await session.execute(
        select(TaskAttempt.created_at, TaskAttempt.outcome, TaskAttempt.reason, TaskAttempt.note)
        .where(TaskAttempt.patient_id == patient.id)
        .order_by(TaskAttempt.created_at.desc())
        .limit(3)
    )
    for at, outcome, reason, note in attempts:
        facts.append(
            f"call result {clinic_time.local(at).date()}: {outcome.value}"
            + (f" ({reason})" if reason else "")
            + (f" — {note}" if note else "")
        )
    open_tasks = await session.scalars(
        select(Task.type).where(Task.patient_id == patient.id, Task.status == TaskStatus.OPEN)
    )
    kinds = [t.value for t in open_tasks]
    if kinds:
        facts.append("open tasks: " + ", ".join(kinds))
    if patient.do_not_call:
        facts.append("asked not to be called")
    return facts


async def brief(session: AsyncSession, patient: Patient, language: str) -> dict[str, Any]:
    facts = await patient_facts(session, patient)
    if not await openai_client.available():
        return {"text": "\n".join(facts), "ai": False}
    lang = "Russian" if language == "ru" else "Uzbek (Latin)"
    llm = get_llm()
    try:
        out = await llm.parse(
            system=(
                "You prepare a call-center operator of a skin clinic for a phone call. From the "
                "facts, write 3-5 short lines: who the patient is, their history with the clinic, "
                "what is open or promised, and what to be careful about. No medical advice, no "
                f"invented facts. Language: {lang}."
            ),
            user="\n".join(mask_pii(f) for f in facts),  # notes may hold phone numbers
            schema=BriefOut,
            cache_key="patient-brief-v1",
        )
    except LlmError:
        return {"text": "\n".join(facts), "ai": False}
    return {"text": out.text.strip(), "ai": True}


# --- weekly digest ----------------------------------------------------------------------------


class DigestTopic(BaseModel):
    text: str
    count: int


class DigestOut(BaseModel):
    summary: str = Field(description="4-6 sentences for the clinic management, Uzbek (Latin)")
    top_questions: list[DigestTopic]
    objections: list[DigestTopic]
    complaints: list[str]
    recommendations: list[str] = Field(description="concrete actions for the call center")


async def digest_stats(session: AsyncSession, date_from: date, date_to: date) -> dict[str, Any]:
    start, end = _range(date_from, date_to)
    rows = (await session.execute(_ready(start, end))).all()
    reasons = dict(
        (
            await session.execute(
                select(TaskAttempt.reason, func.count())
                .where(
                    TaskAttempt.created_at >= start,
                    TaskAttempt.created_at < end,
                    TaskAttempt.reason.is_not(None),
                )
                .group_by(TaskAttempt.reason)
            )
        ).all()
    )
    flags = Counter(f["code"] for a, _ in rows for f in a.red_flags or [])
    scores = [a.score for a, _ in rows if a.score is not None]
    return {
        "calls_analysed": len(rows),
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "red_flags": dict(flags),
        "refusal_reasons": reasons,
        "questions": [q for a, _ in rows for q in a.questions or []][:300],
        "objections": [o for a, _ in rows for o in a.objections or []][:300],
        "complaints": [
            f["quote"] for a, _ in rows for f in a.red_flags or [] if f["code"] == "complaint"
        ][:50],
    }


async def make_digest(session: AsyncSession, date_to: date | None = None) -> AiDigest:
    date_to = date_to or clinic_time.today() - timedelta(days=1)
    date_from = date_to - timedelta(days=6)
    stats = await digest_stats(session, date_from, date_to)
    content, model = None, None
    if stats["calls_analysed"] and await openai_client.available():
        llm = get_llm()
        try:
            out = await llm.parse(
                system=(
                    "You write the weekly call-center digest for the management of Radeski Skin "
                    "Clinic. Group similar questions/objections (count them), list complaints, "
                    "and give 3-5 concrete recommendations. Uzbek (Latin). Base everything only "
                    "on the data given."
                ),
                user=json.dumps(stats, ensure_ascii=False),
                schema=DigestOut,
                cache_key="weekly-digest-v1",
            )
            content, model = out.model_dump(), llm.name
        except LlmError:
            content = None
    digest = AiDigest(
        period_from=date_from, period_to=date_to, stats=stats, content=content, model=model
    )
    session.add(digest)
    await session.flush()
    return digest


async def criteria_all(session: AsyncSession) -> list[QaCriterion]:
    await active_criteria(session)  # seeds the defaults on first use
    return list(await session.scalars(select(QaCriterion).order_by(QaCriterion.sort_order)))


def _code(name: str) -> str:
    slug = "_".join(search_key(name).split())[:30].strip("_")
    return slug or "criterion"


async def add_criterion(session: AsyncSession, **fields: Any) -> QaCriterion:
    """A new QA criterion, scored from the next analysed call on (TZ 4.8.1 #3)."""
    await active_criteria(session)  # the defaults come first
    base = _code(fields["name_uz"])
    taken = set(await session.scalars(select(QaCriterion.code)))
    code, n = base, 2
    while code in taken:
        code, n = f"{base[:36]}_{n}", n + 1
    last = await session.scalar(select(func.max(QaCriterion.sort_order)))
    c = QaCriterion(code=code, sort_order=(last or 0) + 1, **fields)
    session.add(c)
    await session.flush()
    return c


# --- trends, violations, the analysis queue (QA panel, TZ 4.8.1) ------------------------------


def bucket_start(day: date, bucket: str) -> date:
    """The day itself, or the Monday of its week."""
    return day - timedelta(days=day.weekday()) if bucket == "week" else day


def _buckets(date_from: date, date_to: date, bucket: str) -> list[date]:
    out, day = [], bucket_start(date_from, bucket)
    step = timedelta(days=7 if bucket == "week" else 1)
    while day <= date_to:
        out.append(day)
        day += step
    return out


async def trend(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    user_id: uuid.UUID | None = None,
    bucket: str = "day",
) -> dict[str, Any]:
    """Average score per day/week (overall and per operator) and each criterion's pass rate."""
    start, end = _range(date_from, date_to)
    stmt = (
        select(Call.started_at, Call.user_id, CallAnalysis.score, CallAnalysis.criteria)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(
            CallAnalysis.status == AnalysisStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
        )
    )
    if user_id:
        stmt = stmt.where(Call.user_id == user_id)
    rows = (await session.execute(stmt)).all()
    keys = _buckets(date_from, date_to, bucket)
    overall: dict[date, list[int | None]] = {k: [] for k in keys}
    per_user: dict[Any, dict[date, list[int | None]]] = {}
    passed: dict[str, Counter] = {}
    applicable: dict[str, Counter] = {}
    for started_at, uid, score, results in rows:
        k = bucket_start(clinic_time.local(started_at).date(), bucket)
        overall.setdefault(k, []).append(score)
        per_user.setdefault(uid, {}).setdefault(k, []).append(score)
        for r in results or []:
            if r.get("passed") is not None:
                applicable.setdefault(r["code"], Counter())[k] += 1
                passed.setdefault(r["code"], Counter())[k] += bool(r["passed"])
    ids = [u for u in per_user if u is not None]
    names = dict(
        (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    )
    criteria = list(await session.scalars(select(QaCriterion).order_by(QaCriterion.sort_order)))

    def points(scores: dict[date, list[int | None]]) -> list[dict[str, Any]]:
        return [
            {
                "start": k.isoformat(),
                "calls": len(scores.get(k, [])),
                "avg_score": _avg(scores.get(k, [])),
            }
            for k in keys
        ]

    def rates(code: str) -> list[dict[str, Any]]:
        ok, total = passed.get(code, Counter()), applicable.get(code, Counter())
        return [
            {"start": k.isoformat(), "applicable": total[k], "pass_rate": _rate(ok[k], total[k])}
            for k in keys
        ]

    return {
        "bucket": bucket,
        "points": points(overall),
        "operators": sorted(
            (
                {
                    "user_id": uid,
                    "name": names.get(uid, "—") if uid else "—",
                    "calls": sum(len(v) for v in scores.values()),
                    "points": points(scores),
                }
                for uid, scores in per_user.items()
            ),
            key=lambda o: -o["calls"],
        ),
        "criteria": [
            {
                "code": c.code,
                "name_uz": c.name_uz,
                "name_ru": c.name_ru,
                "active": c.active,
                "points": rates(c.code),
            }
            for c in criteria
        ],
    }


async def violations(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    user_id: uuid.UUID | None = None,
    code: str | None = None,
    kind: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Every missed criterion and red flag of the period's calls, newest first, each with the
    quote and the second of the recording it was said at (TZ 4.8.1 #6)."""
    start, end = _range(date_from, date_to)
    # CASE guards jsonb_array_length against a missing list or a JSON null
    v = CallAnalysis.violations
    has_violations = (
        case((func.jsonb_typeof(v) == "array", func.jsonb_array_length(v)), else_=0) > 0
    )
    stmt = (
        select(
            CallAnalysis.id, Call.id, Call.started_at, Call.user_id, User.full_name,
            Call.patient_id, Patient.full_name, CallAnalysis.violations, CallAnalysis.red_flags,
            CallAnalysis.flags_reviewed_at,
        )
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(User, User.id == Call.user_id)
        .outerjoin(Patient, Patient.id == Call.patient_id)
        .where(
            CallAnalysis.status == AnalysisStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
            has_violations | CallAnalysis.has_red_flags,
        )
        .order_by(Call.started_at.desc())
    )  # fmt: skip
    if user_id:
        stmt = stmt.where(Call.user_id == user_id)
    items: list[dict[str, Any]] = []
    counts: Counter = Counter()
    for aid, cid, at, uid, uname, pid, pname, vs, flags, reviewed in await session.execute(stmt):
        found = []
        if kind in ("all", "violation"):
            found += [("violation", v["criterion"], v) for v in vs or []]
        if kind in ("all", "red_flag"):
            found += [("red_flag", f["code"], f) for f in flags or []]
        for k, c, v in found:
            counts[c] += 1
            if code and c != code:
                continue
            items.append(
                {
                    "analysis_id": aid, "call_id": cid, "started_at": at, "user_id": uid,
                    "user_name": uname, "patient_id": pid, "patient_name": pname, "kind": k,
                    "code": c, "quote": v.get("quote") or "", "at": v.get("at"),
                    "reviewed": k == "red_flag" and reviewed is not None,
                }
            )  # fmt: skip
    return {"total": len(items), "items": items[offset : offset + limit], "counts": dict(counts)}


# a recorded call that should have an analysis but has no usable one (yet)
QUEUE_STATUSES = (
    AnalysisStatus.FAILED, AnalysisStatus.PENDING, AnalysisStatus.TRANSCRIBING,
    AnalysisStatus.ANALYZING,
)  # fmt: skip


async def queue(
    session: AsyncSession, date_from: date, date_to: date, *, limit: int = 100
) -> dict[str, Any]:
    """Recorded calls with no analysis yet, a failed one or one still in progress."""
    start, end = _range(date_from, date_to)
    stmt = (
        select(
            Call.id, Call.started_at, Call.direction, Call.talk_seconds, User.full_name,
            Call.patient_id, Patient.full_name, CallAnalysis.status, CallAnalysis.attempts,
            CallAnalysis.error, CallAnalysis.updated_at,
        )
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
        .outerjoin(User, User.id == Call.user_id)
        .outerjoin(Patient, Patient.id == Call.patient_id)
        .where(
            Call.recording_status == RecordingStatus.READY,
            Call.started_at >= start,
            Call.started_at < end,
            CallAnalysis.id.is_(None) | CallAnalysis.status.in_(QUEUE_STATUSES),
        )
        .order_by(Call.started_at.desc())
    )  # fmt: skip
    items = [
        {
            "call_id": cid, "started_at": at, "direction": direction.value,
            "talk_seconds": talk, "user_name": uname, "patient_id": pid, "patient_name": pname,
            "status": st.value if st else "missing", "attempts": attempts or 0, "error": error,
            "updated_at": updated,
        }
        for cid, at, direction, talk, uname, pid, pname, st, attempts, error, updated in (
            await session.execute(stmt)
        )
    ]  # fmt: skip
    return {
        "total": len(items),
        "counts": dict(Counter(i["status"] for i in items)),
        "items": items[:limit],
    }


async def reset_for_retry(session: AsyncSession, call_id: uuid.UUID) -> bool:
    """Give a call's analysis a fresh set of attempts; False when there's nothing to redo
    (no recording, or it's already analysed / skipped)."""
    call = await session.get(Call, call_id)
    if call is None or call.recording_status is not RecordingStatus.READY:
        return False
    a = await session.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
    if a is None:
        return True  # never started: the worker creates the row
    if a.status not in QUEUE_STATUSES:
        return False
    a.status, a.attempts, a.error = AnalysisStatus.PENDING, 0, None
    await session.flush()
    return True
