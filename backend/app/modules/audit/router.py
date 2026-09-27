import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core import clinic_time
from app.core.deps import SessionDep, require_roles
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role, User

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.OWNER))],
)


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID | None
    user_name: str | None
    action: str
    entity: str | None
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None


class AuditPage(BaseModel):
    total: int
    items: list[AuditOut]


@router.get("")
async def list_audit(
    session: SessionDep,
    action: str | None = None,
    # "patient" matches every "patient.*" action (the filter's groups)
    group: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+$")] = None,
    user_id: uuid.UUID | None = None,
    entity: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="bad_range")
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if group:
        filters.append(AuditLog.action.startswith(f"{group}."))
    if user_id:
        filters.append(AuditLog.user_id == user_id)
    if entity:
        filters.append(AuditLog.entity == entity)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id.strip())
    # dates are clinic days (Asia/Tashkent), both ends included
    if date_from:
        filters.append(AuditLog.created_at >= clinic_time.day_bounds(date_from)[0])
    if date_to:
        filters.append(AuditLog.created_at < clinic_time.day_bounds(date_to + timedelta(days=1))[0])

    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    rows = await session.execute(
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(limit)
        .offset(offset)
    )
    items = [
        AuditOut(
            id=log.id,
            created_at=log.created_at,
            user_id=log.user_id,
            user_name=name,
            action=log.action,
            entity=log.entity,
            entity_id=log.entity_id,
            before=log.before,
            after=log.after,
            ip=log.ip,
        )
        for log, name in rows
    ]
    return AuditPage(total=total or 0, items=items)


@router.get("/facets")
async def facets(session: SessionDep) -> dict[str, Any]:
    """Values the filters can take: actions and entities that occur, and who acted."""
    actions = await session.execute(
        select(AuditLog.action, func.count()).group_by(AuditLog.action).order_by(AuditLog.action)
    )
    entities = await session.scalars(
        select(AuditLog.entity)
        .where(AuditLog.entity.is_not(None))
        .distinct()
        .order_by(AuditLog.entity)
    )
    users = await session.execute(
        select(User.id, User.full_name, User.role)
        .where(User.id.in_(select(AuditLog.user_id).where(AuditLog.user_id.is_not(None))))
        .order_by(User.full_name)
    )
    return {
        "actions": [{"action": a, "count": n} for a, n in actions],
        "entities": list(entities),
        "users": [{"id": i, "name": n, "role": r} for i, n, r in users],
    }
