import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.diagnoses.categories import CATEGORY_BY_CODE, normalize_text, suggest_category
from app.modules.diagnoses.models import DiagnosisMapping, MappingMethod, MappingStatus
from app.modules.patients.models import Patient, PatientCondition


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
        session.add(
            DiagnosisMapping(
                text=text,
                category_code=code,
                method=MappingMethod.RULE if code else None,
                status=MappingStatus.SUGGESTED if code else MappingStatus.PENDING,
            )
        )
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
    stmt = update(PatientCondition).values(category_code=approved)
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
    waiting = await session.execute(
        select(DiagnosisMapping.category_code, func.count())
        .where(DiagnosisMapping.status == MappingStatus.SUGGESTED)
        .group_by(DiagnosisMapping.category_code)
    )
    stats: dict[str, dict[str, int]] = {}
    for code, n in patients:
        stats.setdefault(code, {"patients": 0, "suggested_texts": 0})["patients"] = n
    for code, n in waiting:
        stats.setdefault(code, {"patients": 0, "suggested_texts": 0})["suggested_texts"] = n
    return stats
