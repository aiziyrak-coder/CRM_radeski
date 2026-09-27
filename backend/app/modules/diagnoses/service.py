import uuid
from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.diagnoses.categories import CATEGORY_BY_CODE, normalize_text, suggest_category
from app.modules.diagnoses.models import DiagnosisMapping, MappingMethod, MappingStatus
from app.modules.patients.models import MANUAL_CONDITION, Patient, PatientCondition


class UnknownCategoryError(ValueError):
    pass


async def sync(session: AsyncSession) -> Counter[str]:
    """Keys new conditions, creates a mapping (with a rule suggestion) for every new text and
    re-applies approved mappings. Safe to run any time (e.g. after an import)."""
    counts: Counter[str] = Counter()

    unkeyed = await session.execute(
        select(PatientCondition.id, PatientCondition.raw_text).where(
            PatientCondition.text_key.is_(None)
        )
    )
    keyed = [{"id": cid, "text_key": normalize_text(raw)} for cid, raw in unkeyed]
    if keyed:
        # bulk UPDATE by primary key (one executemany instead of a statement per row)
        await session.execute(update(PatientCondition), keyed)
        counts["conditions_keyed"] = len(keyed)

    known = set(await session.scalars(select(DiagnosisMapping.text)))
    texts = set(
        await session.scalars(
            select(PatientCondition.text_key)
            .where(PatientCondition.text_key.is_not(None))
            .distinct()
        )
    )
    for text in sorted(texts - known):
        if not text:
            continue
        code = suggest_category(text)
        # the nightly job and an import can run at the same time: a text added by the other
        # one is skipped instead of failing (and rolling back) the whole run
        inserted = await session.execute(
            pg_insert(DiagnosisMapping)
            .values(
                id=uuid.uuid4(),
                text=text,
                category_code=code,
                method=MappingMethod.RULE if code else None,
                status=MappingStatus.SUGGESTED if code else MappingStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=[DiagnosisMapping.text])
        )
        if inserted.rowcount:
            counts["mappings_suggested" if code else "mappings_pending"] += 1
    await session.flush()
    await apply(session)
    counts["conditions_categorized"] = (
        await session.scalar(
            select(func.count())
            .select_from(PatientCondition)
            .where(PatientCondition.category_code.is_not(None))
        )
        or 0
    )
    return counts


async def apply(session: AsyncSession, texts: list[str] | None = None) -> None:
    """Copies approved categories onto patient_conditions (and clears non-approved ones)."""
    approved = (
        select(DiagnosisMapping.category_code)
        .where(
            DiagnosisMapping.text == PatientCondition.text_key,
            DiagnosisMapping.status == MappingStatus.APPROVED,
        )
        .scalar_subquery()
    )
    # categories staff set on the patient card have no source text: the mapping leaves them alone
    stmt = (
        update(PatientCondition)
        .values(category_code=approved)
        .where(PatientCondition.source != MANUAL_CONDITION)
    )
    if texts is not None:
        stmt = stmt.where(PatientCondition.text_key.in_(texts))
    await session.execute(stmt.execution_options(synchronize_session=False))


async def set_category(
    session: AsyncSession, mapping: DiagnosisMapping, code: str, user_id: uuid.UUID
) -> None:
    if code not in CATEGORY_BY_CODE:
        raise UnknownCategoryError(code)
    if code != mapping.category_code:
        mapping.method = MappingMethod.MANUAL
    mapping.category_code = code
    _approve(mapping, user_id)
    await session.flush()
    await apply(session, [mapping.text])


async def approve(session: AsyncSession, ids: list[uuid.UUID], user_id: uuid.UUID) -> int:
    """Approves suggestions as they are; pending rows without a category are skipped."""
    mappings = list(
        await session.scalars(
            select(DiagnosisMapping).where(
                DiagnosisMapping.id.in_(ids), DiagnosisMapping.category_code.is_not(None)
            )
        )
    )
    for m in mappings:
        _approve(m, user_id)
    await session.flush()
    await apply(session, [m.text for m in mappings])
    return len(mappings)


async def approve_category(
    session: AsyncSession, code: str, user_id: uuid.UUID, method: MappingMethod | None
) -> int:
    """A doctor approves every suggestion of one category at once (e.g. all rule matches for
    "akne" after looking through them); `method=None` takes rule and AI suggestions alike.
    Only still-suggested rows are touched: texts decided meanwhile keep their decision."""
    if code not in CATEGORY_BY_CODE:
        raise UnknownCategoryError(code)
    stmt = select(DiagnosisMapping.id).where(
        DiagnosisMapping.status == MappingStatus.SUGGESTED, DiagnosisMapping.category_code == code
    )
    if method is not None:
        stmt = stmt.where(DiagnosisMapping.method == method)
    ids = list(await session.scalars(stmt))
    return await approve(session, ids, user_id) if ids else 0


async def progress(session: AsyncSession) -> dict[str, int]:
    """How far the doctors' review is (TZ 4.8.4): texts by status and suggestion method, and
    patients whose diagnoses already have an approved category."""
    out = {"total": 0, "approved": 0, "suggested": 0, "pending": 0}
    out |= {"suggested_rule": 0, "suggested_ai": 0}
    for st, method, n in await session.execute(
        select(DiagnosisMapping.status, DiagnosisMapping.method, func.count()).group_by(
            DiagnosisMapping.status, DiagnosisMapping.method
        )
    ):
        out["total"] += n
        out[st.value] += n
        if st is MappingStatus.SUGGESTED and method in (MappingMethod.RULE, MappingMethod.AI):
            out[f"suggested_{method.value}"] += n
    live = (
        select(PatientCondition.patient_id)
        .join(Patient, Patient.id == PatientCondition.patient_id)
        .where(Patient.merged_into_id.is_(None))
    )
    out["patients"] = (
        await session.scalar(select(func.count(func.distinct(live.subquery().c.patient_id)))) or 0
    )
    categorized = live.where(PatientCondition.category_code.is_not(None)).subquery()
    out["patients_categorized"] = (
        await session.scalar(select(func.count(func.distinct(categorized.c.patient_id)))) or 0
    )
    return out


def _approve(mapping: DiagnosisMapping, user_id: uuid.UUID) -> None:
    mapping.status = MappingStatus.APPROVED
    mapping.approved_by = user_id
    mapping.approved_at = datetime.now(UTC)


async def usage_counts(session: AsyncSession, texts: list[str]) -> dict[str, int]:
    rows = await session.execute(
        select(PatientCondition.text_key, func.count(func.distinct(PatientCondition.patient_id)))
        .where(PatientCondition.text_key.in_(texts))
        .group_by(PatientCondition.text_key)
    )
    return dict(rows.all())


async def category_stats(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Per category: patients with an approved diagnosis, and texts still awaiting approval."""
    patients = await session.execute(
        select(
            PatientCondition.category_code, func.count(func.distinct(PatientCondition.patient_id))
        )
        .join(Patient, Patient.id == PatientCondition.patient_id)
        .where(PatientCondition.category_code.is_not(None), Patient.merged_into_id.is_(None))
        .group_by(PatientCondition.category_code)
    )
    texts = await session.execute(
        select(
            DiagnosisMapping.category_code,
            DiagnosisMapping.status,
            DiagnosisMapping.method,
            func.count(),
        )
        .where(DiagnosisMapping.category_code.is_not(None))
        .group_by(DiagnosisMapping.category_code, DiagnosisMapping.status, DiagnosisMapping.method)
    )
    empty = {"patients": 0, "suggested_texts": 0, "suggested_rule": 0, "suggested_ai": 0}
    empty["approved_texts"] = 0
    stats: dict[str, dict[str, int]] = {}
    for code, n in patients:
        stats.setdefault(code, dict(empty))["patients"] = n
    for code, st, method, n in texts:
        row = stats.setdefault(code, dict(empty))
        if st is MappingStatus.APPROVED:
            row["approved_texts"] += n
        elif st is MappingStatus.SUGGESTED:
            row["suggested_texts"] += n
            if method in (MappingMethod.RULE, MappingMethod.AI):
                row[f"suggested_{method.value}"] += n
    return stats


# --- AI suggestions for texts no rule recognised (plan 0.5b) ----------------------------------

AI_BATCH = 40


class _AiItem(BaseModel):
    n: int = Field(description="the number of the text in the list")
    category: str | None = Field(description="category code, or null if none fits")


class _AiBatch(BaseModel):
    items: list[_AiItem]


def _ai_system() -> str:
    lines = [
        "You map free-text diagnoses written by doctors of a dermatology / trichology / "
        "cosmetology clinic in Uzbekistan (Russian, Uzbek, abbreviations, typos, ICD-10 codes) "
        "to one of the clinic's categories. Answer with the category code for every numbered "
        "text; use null when no category fits or the text is not a diagnosis. Never guess "
        "wildly: a doctor approves every answer.",
        "",
        "Categories:",
    ]
    lines += [f"- {c.code}: {c.name_ru} / {c.name_uz}" for c in CATEGORY_BY_CODE.values()]
    return "\n".join(lines)


async def suggest_with_ai(session: AsyncSession, limit: int = 400) -> Counter[str]:
    """Pending mappings get an AI category proposal (status SUGGESTED, method AI); nothing is
    applied to patients until a doctor approves it.

    Runs as a background job (jobs.ai_diagnoses) and commits after every batch. A row is
    re-read under a lock before it is written: a doctor who decided meanwhile keeps the decision."""
    from app.integrations.llm import LlmError, get_llm
    from app.modules.ai.prompts import mask_pii

    counts: Counter[str] = Counter()
    pending = list(
        await session.execute(
            select(DiagnosisMapping.id, DiagnosisMapping.text)
            .where(DiagnosisMapping.status == MappingStatus.PENDING)
            .order_by(DiagnosisMapping.text)
            .limit(limit)
        )
    )
    llm = get_llm()
    system = _ai_system()
    for start in range(0, len(pending), AI_BATCH):
        chunk = pending[start : start + AI_BATCH]
        try:
            out = await llm.parse(
                system=system,
                user="\n".join(f"{i}. {mask_pii(text)}" for i, (_, text) in enumerate(chunk, 1)),
                schema=_AiBatch,
                cache_key="diagnosis-categories-v1",
            )
        except LlmError:
            counts["failed_batches"] += 1
            continue
        proposals = {
            chunk[item.n - 1][0]: item.category
            for item in out.items
            if 1 <= item.n <= len(chunk) and item.category in CATEGORY_BY_CODE
        }
        still_pending = await session.scalars(
            select(DiagnosisMapping)
            .where(
                DiagnosisMapping.id.in_(proposals),
                DiagnosisMapping.status == MappingStatus.PENDING,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        for mapping in still_pending:
            mapping.category_code = proposals[mapping.id]
            mapping.method = MappingMethod.AI
            mapping.status = MappingStatus.SUGGESTED
            counts["suggested"] += 1
        counts["checked"] += len(chunk)
        await session.commit()  # each batch is kept even if a later one fails
    return counts


AI_LOCK = "lock:ai-diagnoses"
AI_LOCK_SECONDS = 3600


async def ai_running() -> bool:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        return bool(await redis.exists(AI_LOCK))
    finally:
        await redis.aclose()


async def run_ai_suggestions(session: AsyncSession, limit: int = 400) -> Counter[str] | None:
    """The background job: one run at a time (a second click doesn't pay for the same texts)."""
    redis = Redis.from_url(get_settings().redis_url)
    try:
        if not await redis.set(AI_LOCK, 1, nx=True, ex=AI_LOCK_SECONDS):
            return None
        try:
            return await suggest_with_ai(session, limit=limit)
        finally:
            await redis.delete(AI_LOCK)
    finally:
        await redis.aclose()
