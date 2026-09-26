"""Event handlers of the AI module (imported by app.main and the workers)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import on
from app.modules.ai import service


@on("task.result")
async def _operator_review(session: AsyncSession, p: dict[str, Any]) -> None:
    if p.get("analysis_id"):
        await service.record_review(
            session, p["analysis_id"], outcome=p["outcome"].value, reason=p.get("reason"),
            user_id=p["user_id"],
        )  # fmt: skip
