"""Event handlers of the AI module (imported by app.main and the workers)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import on
from app.modules.ai import service
from app.modules.ai.models import CallAnalysis
from app.modules.telephony.models import Call


@on("task.result")
async def _operator_review(session: AsyncSession, p: dict[str, Any]) -> None:
    analysis_id = p.get("analysis_id")
    if not analysis_id:
        return
    # only an analysis of a call made from this very task can be confirmed by its result;
    # any other id (stale screen, crafted request) is ignored
    own = await session.scalar(
        select(CallAnalysis.id)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(CallAnalysis.id == analysis_id, Call.task_id == p["task"].id)
    )
    if own is None:
        return
    await service.record_review(
        session, analysis_id, outcome=p["outcome"].value, reason=p.get("reason"),
        user_id=p["user_id"],
    )  # fmt: skip
