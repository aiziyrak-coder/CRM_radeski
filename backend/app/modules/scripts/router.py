import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.scripts.models import Script
from app.modules.scripts.seed import SCRIPTS
from app.modules.users.models import Language, Role, User

router = APIRouter(prefix="/scripts", tags=["scripts"])
Reader = Annotated[
    User, Depends(require_roles(Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.ADMIN))
]
Editor = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


class ScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    language: Language
    title: str
    body: str
    sort_order: int
    updated_at: datetime


class ScriptIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=20000)


async def seed_if_empty(session: AsyncSession) -> int:
    if await session.scalar(select(Script.id).limit(1)):
        return 0
    for item in SCRIPTS:
        session.add(Script(**item))
    await session.commit()
    return len(SCRIPTS)


@router.get("")
async def list_scripts(
    session: SessionDep, _: Reader, language: Language | None = None
) -> list[ScriptOut]:
    stmt = select(Script).order_by(Script.sort_order, Script.language)
    if language:
        stmt = stmt.where(Script.language == language)
    return [ScriptOut.model_validate(s) for s in await session.scalars(stmt)]


@router.put("/{code}/{language}")
async def update_script(
    code: str,
    language: Language,
    body: ScriptIn,
    request: Request,
    session: SessionDep,
    user: Editor,
) -> ScriptOut:
    script = await session.scalar(
        select(Script).where(Script.code == code, Script.language == language)
    )
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="script_not_found")
    before = {"title": script.title, "body": script.body}
    script.title, script.body, script.updated_by = body.title, body.body, user.id
    audit.record(
        session, "script.update", user_id=user.id, entity="script", entity_id=f"{code}:{language}",
        before=before, after=body.model_dump(), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return ScriptOut.model_validate(script)
