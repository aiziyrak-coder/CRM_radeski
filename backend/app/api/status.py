"""What is connected and what needs attention (home page). Staff only: /health stays minimal."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, require_roles
from app.integrations import openai_client
from app.integrations.instagram import get_instagram
from app.integrations.sms import get_sms_sender
from app.integrations.telegram import get_telegram
from app.modules.ai.models import AnalysisStatus, CallAnalysis
from app.modules.messaging.models import Conversation, Message, MessageStatus
from app.modules.telephony.models import (
    UNANSWERED_INBOUND,
    Call,
    CallDirection,
    RecordingStatus,
)
from app.modules.users.models import Role, User

router = APIRouter(prefix="/system", tags=["system"])
Staff = Annotated[
    User, Depends(require_roles(Role.OPERATOR, Role.SUPERVISOR, Role.OWNER, Role.ADMIN))
]


async def _count(session: SessionDep, stmt) -> int:
    return await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


@router.get("/status")
async def system_status(session: SessionDep, user: Staff) -> dict[str, Any]:
    s = get_settings()
    start, end = clinic_time.day_bounds(clinic_time.today())
    week_ago = datetime.now(UTC) - timedelta(days=7)
    out: dict[str, Any] = {
        "today": {
            "missed_calls": await _count(
                session,
                select(Call.id).where(
                    Call.direction == CallDirection.IN,
                    Call.status.in_(UNANSWERED_INBOUND),
                    Call.started_at >= start,
                    Call.started_at < end,
                ),
            ),
            "unread_chats": await _count(
                session, select(Conversation.id).where(Conversation.unread > 0)
            ),
        },
    }
    if user.role is not Role.OPERATOR:
        out["qa"] = {
            "red_flags_open": await _count(
                session,
                select(CallAnalysis.id).where(
                    CallAnalysis.has_red_flags,
                    CallAnalysis.flags_reviewed_at.is_(None),
                    CallAnalysis.created_at > week_ago,
                ),
            ),
        }
        last_call = await session.scalar(select(func.max(Call.started_at)))
        sms = get_sms_sender()
        out["integrations"] = {
            "telephony": bool(s.pbx_api_secret),
            "trunk": bool(s.sip_host),
            "last_call_at": last_call,
            "ai": openai_client.enabled(),
            "telegram": get_telegram() is not None,
            "instagram": get_instagram() is not None,
            "sms": sms.name if sms else None,
        }
        out["attention"] = {
            "recordings_failed": await _count(
                session,
                select(Call.id).where(
                    Call.recording_status == RecordingStatus.FAILED, Call.started_at > week_ago
                ),
            ),
            "analyses_failed": await _count(
                session,
                select(CallAnalysis.id).where(
                    CallAnalysis.status == AnalysisStatus.FAILED,
                    CallAnalysis.created_at > week_ago,
                ),
            ),
            "messages_failed": await _count(
                session,
                select(Message.id).where(
                    Message.status == MessageStatus.FAILED, Message.created_at > week_ago
                ),
            ),
            "messages_queued": await _count(
                session, select(Message.id).where(Message.status == MessageStatus.QUEUED)
            ),
        }
    return out
