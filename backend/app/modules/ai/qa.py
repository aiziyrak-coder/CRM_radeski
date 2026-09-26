"""QA panel figures (plan 4.5), pre-call brief and weekly digest (plan 4.6)."""

import json
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.integrations import openai_client
from app.integrations.llm import LlmError, get_llm
from app.modules.ai.models import AiDigest, AnalysisStatus, CallAnalysis, QaCriterion
from app.modules.ai.service import active_criteria
from app.modules.patients.models import Patient, PatientCondition
from app.modules.scheduling.models import Appointment
from app.modules.tasks.models import Task, TaskAttempt, TaskStatus
from app.modules.telephony.models import Call
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
    stmt = _ready(start, end)
    if user_id:
        stmt = stmt.where(Call.user_id == user_id)
    rows = (await session.execute(stmt)).all()
    names = dict((await session.execute(select(User.id, User.full_name))).all())
    per_user: dict[Any, list[CallAnalysis]] = {}
    for a, call in rows:
        per_user.setdefault(call.user_id, []).append(a)
    criteria = list(await session.scalars(select(QaCriterion).order_by(QaCriterion.sort_order)))
    passed, applicable = Counter(), Counter()
    for a, _ in rows:
        for r in a.criteria or []:
            if r.get("passed") is not None:
                applicable[r["code"]] += 1
                passed[r["code"]] += bool(r["passed"])
    return {
        "analysed": len(rows),
        "avg_score": _avg([a.score for a, _ in rows]),
        "red_flags_open": sum(1 for a, _ in rows if a.has_red_flags and not a.flags_reviewed_at),
        "operators": sorted(
            (
                {
                    "user_id": uid,
                    "name": names.get(uid, "—") if uid else "—",
                    "calls": len(items),
                    "avg_score": _avg([a.score for a in items]),
                    "red_flags": sum(a.has_red_flags for a in items),
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
            Counter(a.review.value for a, _ in rows if a.review is not None)
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
    if not openai_client.enabled():
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
            user="\n".join(facts),
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
    if openai_client.enabled() and stats["calls_analysed"]:
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
