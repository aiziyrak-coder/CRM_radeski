import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.diagnoses import service
from app.modules.diagnoses.categories import CATEGORIES, Specialty
from app.modules.diagnoses.models import DiagnosisMapping, MappingMethod, MappingStatus
from app.modules.patients.models import PatientCondition
from app.modules.users.models import Role, User

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])

# registrars use the category filter and badges on the patients page
Reader = Annotated[
    User,
    Depends(require_roles(Role.ADMIN, Role.DOCTOR, Role.SUPERVISOR, Role.OPERATOR, Role.REGISTRAR)),
]
# TZ 4.8.4: a doctor reviews and approves the mapping
Approver = Annotated[User, Depends(require_roles(Role.ADMIN, Role.DOCTOR))]


class CategoryOut(BaseModel):
    code: str
    name_uz: str
    name_ru: str
    specialty: Specialty
    patients: int
    suggested_texts: int
    suggested_rule: int = 0
    suggested_ai: int = 0
    approved_texts: int = 0


class MappingOut(BaseModel):
    id: uuid.UUID
    text: str
    category_code: str | None
    method: MappingMethod | None
    status: MappingStatus
    patients: int


class MappingPage(BaseModel):
    total: int
    items: list[MappingOut]
    by_status: dict[str, int]


class SetCategoryIn(BaseModel):
    category_code: str


class ApproveIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class ApproveCategoryIn(BaseModel):
    category_code: str = Field(max_length=50)
    # "rule" (default): only the keyword/ICD matches; null: rule and AI suggestions alike
    method: MappingMethod | None = MappingMethod.RULE


@router.get("/categories")
async def categories(session: SessionDep, _: Reader) -> list[CategoryOut]:
    stats = await service.category_stats(session)
    return [
        CategoryOut(
            code=c.code,
            name_uz=c.name_uz,
            name_ru=c.name_ru,
            specialty=c.specialty,
            **stats.get(c.code, {"patients": 0, "suggested_texts": 0}),
        )
        for c in CATEGORIES
    ]


@router.get("/mappings")
async def list_mappings(
    session: SessionDep,
    _: Reader,
    status_: Annotated[MappingStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MappingPage:
    filters = []
    if status_:
        filters.append(DiagnosisMapping.status == status_)
    if category:
        filters.append(DiagnosisMapping.category_code == category)
    if q and q.strip():
        filters.append(DiagnosisMapping.text.contains(q.strip().lower()))

    total = await session.scalar(select(func.count()).select_from(DiagnosisMapping).where(*filters))
    by_status = dict(
        (
            await session.execute(
                select(DiagnosisMapping.status, func.count()).group_by(DiagnosisMapping.status)
            )
        ).all()
    )
    # most common diagnoses first: approving them covers the most patients
    usage = (
        select(func.count(func.distinct(PatientCondition.patient_id)))
        .where(PatientCondition.text_key == DiagnosisMapping.text)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(DiagnosisMapping, usage.label("patients"))
        .where(*filters)
        .order_by(usage.desc(), DiagnosisMapping.text)
        .limit(limit)
        .offset(offset)
    )
    items = [
        MappingOut(
            id=m.id,
            text=m.text,
            category_code=m.category_code,
            method=m.method,
            status=m.status,
            patients=n,
        )
        for m, n in rows
    ]
    return MappingPage(
        total=total or 0, items=items, by_status={str(k): v for k, v in by_status.items()}
    )


@router.put("/mappings/{mapping_id}")
async def set_category(
    mapping_id: uuid.UUID,
    body: SetCategoryIn,
    request: Request,
    session: SessionDep,
    user: Approver,
) -> MappingOut:
    mapping = await session.get(DiagnosisMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mapping_not_found")
    before = {"category_code": mapping.category_code, "status": mapping.status.value}
    try:
        await service.set_category(session, mapping, body.category_code, user.id)
    except service.UnknownCategoryError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_category"
        ) from None
    audit.record(
        session,
        "diagnosis.map",
        user_id=user.id,
        entity="diagnosis_mapping",
        entity_id=mapping.id,
        before=before,
        after={"text": mapping.text, "category_code": mapping.category_code},
        ip=client_ip(request),
    )
    await session.commit()
    patients = (await service.usage_counts(session, [mapping.text])).get(mapping.text, 0)
    return MappingOut(
        id=mapping.id,
        text=mapping.text,
        category_code=mapping.category_code,
        method=mapping.method,
        status=mapping.status,
        patients=patients,
    )


@router.post("/mappings/approve")
async def approve(
    body: ApproveIn, request: Request, session: SessionDep, user: Approver
) -> dict[str, int]:
    approved = await service.approve(session, body.ids, user.id)
    audit.record(
        session,
        "diagnosis.approve",
        user_id=user.id,
        after={"requested": len(body.ids), "approved": approved},
        ip=client_ip(request),
    )
    await session.commit()
    return {"approved": approved}


@router.post("/mappings/approve-category")
async def approve_category(
    body: ApproveCategoryIn, request: Request, session: SessionDep, user: Approver
) -> dict[str, int]:
    """Bulk review: the doctor approves every suggestion of one category after looking at the
    list (the approval is still theirs, recorded with their name)."""
    if body.method is MappingMethod.MANUAL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="validation_error")
    try:
        approved = await service.approve_category(session, body.category_code, user.id, body.method)
    except service.UnknownCategoryError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_category"
        ) from None
    audit.record(
        session,
        "diagnosis.approve_category",
        user_id=user.id,
        entity="diagnosis_category",
        entity_id=body.category_code,
        after={"method": body.method.value if body.method else None, "approved": approved},
        ip=client_ip(request),
    )
    await session.commit()
    return {"approved": approved}


@router.get("/progress")
async def progress(session: SessionDep, _: Reader) -> dict[str, int]:
    return await service.progress(session)


def _enqueue_ai() -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task("jobs.ai_diagnoses")


@router.post("/ai-suggest", status_code=status.HTTP_202_ACCEPTED)
async def ai_suggest(_: Approver) -> dict[str, int]:
    """Starts the AI proposals in the background (minutes for a few hundred texts: longer than
    a browser request may wait); the list shows them as they arrive."""
    from app.integrations.openai_client import available, enabled

    if not enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_disabled")
    if not await available():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="ai_budget_exceeded")
    if await service.ai_running():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already_running")
    _enqueue_ai()
    return {"queued": 1}


@router.post("/sync")
async def sync(session: SessionDep, _: Approver) -> dict[str, int]:
    counts = await service.sync(session)
    await session.commit()
    return dict(counts)
