import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, require_roles
from app.integrations import openai_client
from app.modules.ai import qa
from app.modules.ai.models import AiDigest, CallAnalysis, QaCriterion
from app.modules.patients.models import Patient
from app.modules.telephony.models import Call
from app.modules.users.models import Role, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

MANAGERS = (Role.SUPERVISOR, Role.ADMIN, Role.OWNER)
Manager = Annotated[User, Depends(require_roles(*MANAGERS))]
Editor = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]
Agent = Annotated[User, Depends(require_roles(Role.OPERATOR, *MANAGERS))]
BRIEF_TTL = 6 * 3600


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    date_to = date_to or clinic_time.today()
    # a year outside 2000-2100 is a typo (and 9999-12-31 overflows the day arithmetic)
    if not all(2000 <= d.year <= 2100 for d in (date_from or date_to, date_to)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_period")
    date_from = date_from or date_to - timedelta(days=6)
    if date_from > date_to or (date_to - date_from).days > 366:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_period")
    return date_from, date_to


@router.get("/status")
async def ai_status(_: CurrentUser) -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": openai_client.enabled(),
        "stt_model": settings.ai_stt_model,
        "llm_model": settings.ai_llm_model,
        "spent_today_usd": round(await openai_client.spent_today(), 4),
        "daily_budget_usd": settings.ai_daily_budget_usd,
    }


# --- one call ---------------------------------------------------------------------------------


class AnalysisOut(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    status: str
    error: str | None
    stt_model: str | None
    llm_model: str | None
    prompt_version: str | None
    transcript: list[dict[str, Any]] | None
    language: str | None
    conversation_type: str | None
    score: int | None
    criteria: list[dict[str, Any]] | None
    violations: list[dict[str, Any]] | None
    red_flags: list[dict[str, Any]] | None
    summary: str | None
    suggested_outcome: str | None
    suggested_reason: str | None
    extracted: dict[str, Any] | None
    questions: list[str] | None
    objections: list[str] | None
    review: str | None
    corrections: dict[str, Any] | None
    flags_reviewed_at: datetime | None


@router.get("/calls/{call_id}")
async def call_analysis(call_id: uuid.UUID, session: SessionDep, user: Agent) -> AnalysisOut:
    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="call_not_found")
    # same rule as listening to the recording: operators see their own calls
    if user.role not in MANAGERS and call.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    a = await session.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="analysis_not_found")
    return AnalysisOut(
        **{f: getattr(a, f) for f in AnalysisOut.model_fields if f not in ("status", "review")},
        status=a.status.value,
        review=a.review.value if a.review else None,
    )


@router.post("/calls/{call_id}/flags-reviewed", status_code=status.HTTP_204_NO_CONTENT)
async def flags_reviewed(call_id: uuid.UUID, session: SessionDep, user: Editor) -> None:
    a = await session.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="analysis_not_found")
    a.flags_reviewed_by, a.flags_reviewed_at = user.id, datetime.now(UTC)
    await session.commit()


# --- QA panel ---------------------------------------------------------------------------------


@router.get("/qa/overview")
async def qa_overview(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    await qa.criteria_all(session)
    return await qa.overview(session, *_period(date_from, date_to), user_id)


@router.get("/qa/calls")
async def qa_calls(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    user_id: uuid.UUID | None = None,
    flagged: bool = False,
    order: Literal["recent", "worst", "best"] = "recent",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return await qa.calls(
        session, *_period(date_from, date_to), user_id=user_id, flagged=flagged, order=order,
        limit=limit,
    )  # fmt: skip


@router.get("/qa/trend")
async def qa_trend(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    user_id: uuid.UUID | None = None,
    bucket: Literal["day", "week"] = "day",
) -> dict[str, Any]:
    await qa.criteria_all(session)
    return await qa.trend(session, *_period(date_from, date_to), user_id=user_id, bucket=bucket)


@router.get("/qa/violations")
async def qa_violations(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    user_id: uuid.UUID | None = None,
    code: Annotated[str | None, Query(max_length=40)] = None,
    kind: Literal["all", "violation", "red_flag"] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Missed criteria and red flags across calls, each with its quote and moment."""
    return await qa.violations(
        session, *_period(date_from, date_to), user_id=user_id, code=code, kind=kind,
        limit=limit, offset=offset,
    )  # fmt: skip


@router.get("/qa/queue")
async def qa_queue(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    """Recorded calls without a usable analysis: failed, waiting or never started."""
    return await qa.queue(session, *_period(date_from, date_to))


def _enqueue_analysis(call_id: uuid.UUID) -> bool:
    from app.workers.celery_app import celery_app

    try:
        celery_app.send_task("jobs.analyze_call", args=[str(call_id)])
    except Exception:  # broker down: the half-hourly retry job still picks it up
        log.warning("could not queue the analysis of call %s", call_id)
        return False
    return True


class RetryIn(BaseModel):
    call_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


@router.post("/qa/retry")
async def qa_retry(body: RetryIn, session: SessionDep, _: Editor) -> dict[str, int]:
    """Supervisor: analyse these calls again with a fresh set of attempts."""
    if not openai_client.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ai_disabled")
    ids = list(dict.fromkeys(body.call_ids))
    reset = [cid for cid in ids if await qa.reset_for_retry(session, cid)]
    await session.commit()
    for cid in reset:
        _enqueue_analysis(cid)
    return {"queued": len(reset), "skipped": len(ids) - len(reset)}


class CriterionOut(BaseModel):
    id: uuid.UUID
    code: str
    name_uz: str
    name_ru: str
    description: str
    weight: int
    active: bool
    sort_order: int


class CriterionIn(BaseModel):
    name_uz: str = Field(min_length=2, max_length=255)
    name_ru: str = Field(min_length=2, max_length=255)
    description: str = Field(min_length=5, max_length=2000)
    weight: int = Field(ge=0, le=100)
    active: bool


@router.get("/criteria")
async def criteria(session: SessionDep, _: Manager) -> list[CriterionOut]:
    rows = await qa.criteria_all(session)
    await session.commit()
    return [CriterionOut.model_validate(c, from_attributes=True) for c in rows]


@router.post("/criteria", status_code=status.HTTP_201_CREATED)
async def create_criterion(body: CriterionIn, session: SessionDep, _: Editor) -> CriterionOut:
    """A new criterion; its code is derived from the Uzbek name (shown to the model)."""
    c = await qa.add_criterion(session, **body.model_dump())
    await session.commit()
    return CriterionOut.model_validate(c, from_attributes=True)


@router.put("/criteria/{criterion_id}")
async def update_criterion(
    criterion_id: uuid.UUID, body: CriterionIn, session: SessionDep, _: Editor
) -> CriterionOut:
    c = await session.get(QaCriterion, criterion_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="criterion_not_found")
    for field, value in body.model_dump().items():
        setattr(c, field, value)
    await session.commit()
    return CriterionOut.model_validate(c, from_attributes=True)


# --- digest -----------------------------------------------------------------------------------


class DigestOut(BaseModel):
    id: uuid.UUID
    period_from: date
    period_to: date
    model: str | None
    stats: dict[str, Any]
    content: dict[str, Any] | None
    created_at: datetime


@router.get("/digest")
async def latest_digest(session: SessionDep, _: Manager) -> DigestOut | None:
    d = await session.scalar(select(AiDigest).order_by(AiDigest.created_at.desc()).limit(1))
    return DigestOut.model_validate(d, from_attributes=True) if d else None


class DigestItem(BaseModel):
    id: uuid.UUID
    period_from: date
    period_to: date
    created_at: datetime
    calls_analysed: int
    avg_score: int | None
    has_content: bool


@router.get("/digests")
async def digests(
    session: SessionDep, _: Manager, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> list[DigestItem]:
    """Digest history, newest first (the weekly job and the ones made by hand)."""
    rows = await session.scalars(select(AiDigest).order_by(AiDigest.created_at.desc()).limit(limit))
    return [
        DigestItem(
            id=d.id, period_from=d.period_from, period_to=d.period_to, created_at=d.created_at,
            calls_analysed=(d.stats or {}).get("calls_analysed", 0),
            avg_score=(d.stats or {}).get("avg_score"), has_content=d.content is not None,
        )
        for d in rows
    ]  # fmt: skip


@router.get("/digests/{digest_id}")
async def digest(digest_id: uuid.UUID, session: SessionDep, _: Manager) -> DigestOut:
    d = await session.get(AiDigest, digest_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="digest_not_found")
    return DigestOut.model_validate(d, from_attributes=True)


@router.post("/digest")
async def make_digest(session: SessionDep, _: Editor) -> DigestOut:
    d = await qa.make_digest(session)
    await session.commit()
    return DigestOut.model_validate(d, from_attributes=True)


# --- pre-call brief ---------------------------------------------------------------------------


@router.get("/patients/{patient_id}/brief")
async def patient_brief(
    patient_id: uuid.UUID,
    session: SessionDep,
    _: Agent,
    lang: Literal["uz", "ru"] = "uz",
) -> dict[str, Any]:
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    key = f"brief:{patient_id}:{lang}"
    try:
        if cached := await redis.get(key):
            return {"text": cached, "ai": True}
        result = await qa.brief(session, patient, lang)
        if result["ai"]:
            await redis.set(key, result["text"], ex=BRIEF_TTL)
        return result
    finally:
        await redis.aclose()
