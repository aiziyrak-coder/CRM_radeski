import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

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
    user_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if user_id:
        filters.append(AuditLog.user_id == user_id)

    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    rows = await session.execute(
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
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
