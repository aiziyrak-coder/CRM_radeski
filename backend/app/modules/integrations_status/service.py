"""Admin integrations page: what each external connection is, whether it is configured, when
it last worked, what is missing to connect it, and a safe test for the ones that allow one.

Tests only read (list models, getMe, balance, a public site list): nothing is sent to patients
and no AI tokens are spent. Secrets are never returned — only which variables are empty."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import openai
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.integrations import openai_client
from app.integrations.instagram import InstagramClient
from app.integrations.site import SiteClient
from app.integrations.sms import SendError
from app.integrations.telegram import TelegramBot
from app.modules.ai.models import AnalysisStatus, CallAnalysis
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Branch, Doctor, Service
from app.modules.integrations_status import heartbeat
from app.modules.leads.models import Lead, LeadChannel
from app.modules.messaging.models import Channel, Conversation, Direction, Message, MessageStatus
from app.modules.telephony.models import Call, CallDirection, RecordingStatus

TESTS = ("openai", "telegram", "instagram", "sms", "site")
# tests replace the HTTP layer of every adapter with a fake transport
_transport: httpx.AsyncBaseTransport | None = None


def _missing(**values: Any) -> list[str]:
    return [name for name, value in values.items() if not value]


def _item(key: str, *, missing: list[str], facts: dict[str, Any], state: str | None = None,
          test: str | None = None, docs: str) -> dict[str, Any]:  # fmt: skip
    configured = not missing
    return {
        "key": key,
        "configured": configured,
        "state": state if configured and state else ("ok" if configured else "off"),
        "missing": missing,
        "facts": facts,
        "test": test if configured else None,
        "docs": docs,
    }


def _age_state(at: datetime | str | None, warn_after: timedelta) -> str:
    if at is None:
        return "warning"
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    return "ok" if datetime.now(UTC) - at < warn_after else "warning"


async def _scalar(session: AsyncSession, stmt) -> Any:
    return await session.scalar(stmt)


async def _count(session: AsyncSession, model, *where) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*where)) or 0


async def _last_inbound(session: AsyncSession, channel: Channel) -> datetime | None:
    return await session.scalar(
        select(func.max(Message.created_at))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.channel == channel, Message.direction == Direction.IN)
    )


async def status(session: AsyncSession) -> list[dict[str, Any]]:
    s = get_settings()
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    start, _ = clinic_time.day_bounds(clinic_time.today())
    items: list[dict[str, Any]] = []

    # --- telephony ---------------------------------------------------------------------------
    last_call = await _scalar(session, select(func.max(Call.started_at)))
    items.append(
        _item(
            "telephony",
            missing=_missing(PBX_API_SECRET=s.pbx_api_secret, PBX_SIP_SECRET=s.pbx_sip_secret),
            facts={
                "last_call_at": last_call,
                "calls_today": await _count(session, Call, Call.started_at >= start),
                "extensions": " ".join(s.pbx_extensions.split()),
                "recordings_failed_7d": await _count(
                    session,
                    Call,
                    Call.recording_status == RecordingStatus.FAILED,
                    Call.started_at > week_ago,
                ),  # fmt: skip
            },
            state=_age_state(last_call, timedelta(days=3)),
            docs="docs/06_TELEFONIYA.md",
        )
    )
    inbound = (Call.direction == CallDirection.IN,)
    last_in = await _scalar(session, select(func.max(Call.started_at)).where(*inbound))
    items.append(
        _item(
            "trunk",
            missing=_missing(SIP_HOST=s.sip_host),
            facts={
                "sip_host": s.sip_host or None,
                "last_inbound_at": last_in,
                "inbound_today": await _count(session, Call, *inbound, Call.started_at >= start),
            },
            state=_age_state(last_in, timedelta(days=2)),
            docs="docs/06_TELEFONIYA.md",
        )
    )

    # --- OpenAI ------------------------------------------------------------------------------
    spent = round(await openai_client.spent_today(), 4)
    budget = s.ai_daily_budget_usd
    failed = await _count(
        session, CallAnalysis, CallAnalysis.status == AnalysisStatus.FAILED,
        CallAnalysis.created_at > week_ago,
    )  # fmt: skip
    ai_state = "warning" if (budget > 0 and spent >= budget) or failed else "ok"
    items.append(
        _item(
            "openai",
            missing=_missing(OPENAI_API_KEY=s.openai_api_key),
            facts={
                "spent_today_usd": spent,
                "daily_budget_usd": budget,
                "llm_model": s.ai_llm_model,
                "stt_model": s.ai_stt_model,
                "service_tier": s.ai_service_tier or None,
                "analyses_ready_7d": await _count(
                    session,
                    CallAnalysis,
                    CallAnalysis.status == AnalysisStatus.READY,
                    CallAnalysis.created_at > week_ago,
                ),  # fmt: skip
                "analyses_failed_7d": failed,
                "last_analysis_at": await _scalar(
                    session,
                    select(func.max(CallAnalysis.updated_at)).where(
                        CallAnalysis.status == AnalysisStatus.READY
                    ),
                ),
            },
            state=ai_state,
            test="openai",
            docs="docs/07_AI.md",
        )
    )

    # --- chats and SMS -----------------------------------------------------------------------
    items.append(
        _item(
            "telegram",
            missing=_missing(
                TELEGRAM_BOT_TOKEN=s.telegram_bot_token,
                TELEGRAM_WEBHOOK_SECRET=s.telegram_webhook_secret,
            ),
            facts={
                "last_inbound_at": await _last_inbound(session, Channel.TELEGRAM),
                "conversations": await _count(
                    session, Conversation, Conversation.channel == Channel.TELEGRAM
                ),
                "webhook_url": f"{s.public_url.rstrip('/')}/api/integrations/telegram/webhook",
            },
            test="telegram",
            docs="docs/08_KANALLAR.md",
        )
    )
    items.append(
        _item(
            "instagram",
            missing=_missing(
                INSTAGRAM_ACCESS_TOKEN=s.instagram_access_token,
                INSTAGRAM_APP_SECRET=s.instagram_app_secret,
                INSTAGRAM_VERIFY_TOKEN=s.instagram_verify_token,
                INSTAGRAM_USER_ID=s.instagram_user_id,
            ),
            facts={
                "last_inbound_at": await _last_inbound(session, Channel.INSTAGRAM),
                "conversations": await _count(
                    session, Conversation, Conversation.channel == Channel.INSTAGRAM
                ),
                "webhook_url": f"{s.public_url.rstrip('/')}/api/integrations/instagram/webhook",
            },
            test="instagram",
            docs="docs/08_KANALLAR.md",
        )
    )
    provider = s.sms_provider
    if provider == "eskiz":
        sms_missing = _missing(ESKIZ_EMAIL=s.eskiz_email, ESKIZ_PASSWORD=s.eskiz_password)
    elif provider == "playmobile":
        sms_missing = _missing(
            PLAYMOBILE_LOGIN=s.playmobile_login, PLAYMOBILE_PASSWORD=s.playmobile_password
        )
    else:
        sms_missing = ["SMS_PROVIDER"]
    sms_out = (Conversation.channel == Channel.SMS, Message.direction == Direction.OUT)
    sms_failed = await session.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(*sms_out, Message.status == MessageStatus.FAILED, Message.created_at > week_ago)
    )
    items.append(
        _item(
            "sms",
            missing=sms_missing,
            facts={
                "provider": provider or None,
                "last_sent_at": await session.scalar(
                    select(func.max(Message.sent_at))
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(*sms_out)
                ),
                "failed_7d": sms_failed or 0,
                "delivery_reports": bool(s.eskiz_callback_secret) if provider == "eskiz" else None,
            },
            state="warning" if sms_failed else "ok",
            # Playmobile has no balance request: nothing safe to test without sending an SMS
            test="sms" if provider == "eskiz" else None,
            docs="docs/08_KANALLAR.md",
        )
    )

    # --- radeski.uz --------------------------------------------------------------------------
    site_leads = (Lead.channel == LeadChannel.WEBSITE,)
    items.append(
        _item(
            "site_webhook",
            missing=_missing(SITE_WEBHOOK_SECRET=s.site_webhook_secret),
            facts={
                # the webhook and the polling both create website inquiries (one per site id)
                "last_request_at": await _scalar(
                    session, select(func.max(Lead.created_at)).where(*site_leads)
                ),
                "requests_7d": await _count(session, Lead, *site_leads, Lead.created_at > week_ago),
                "webhook_url": f"{s.public_url.rstrip('/')}/api/integrations/site/appointments",
            },
            docs="docs/05_SAYT_INTEGRATSIYA.md",
        )
    )
    poll = await heartbeat.read("site_poll")
    poll_state = (
        "error" if poll.get("failing") else _age_state(poll.get("last_ok"), timedelta(minutes=30))
    )
    items.append(
        _item(
            "site_polling",
            missing=_missing(
                SITE_ADMIN_USERNAME=s.site_admin_username,
                SITE_ADMIN_PASSWORD=s.site_admin_password,
            ),
            facts={
                "last_run_at": poll.get("last_run"),
                "last_success_at": poll.get("last_ok"),
                "last_error": poll.get("error") if poll.get("failing") else None,
                "interval_minutes": 5,
            },
            state=poll_state,
            test="site",
            docs="docs/05_SAYT_INTEGRATSIYA.md",
        )
    )
    sync = await heartbeat.read("catalog_sync")
    manual = await _scalar(
        session, select(func.max(AuditLog.created_at)).where(AuditLog.action == "catalog.sync")
    )
    last_ok = max(
        (d for d in (sync.get("last_ok") and datetime.fromisoformat(sync["last_ok"]), manual) if d),
        default=None,
    )
    failing = sync.get("failing") and (
        manual is None or manual < datetime.fromisoformat(sync["last_error_at"])
    )
    items.append(
        _item(
            "catalog_sync",
            missing=_missing(SITE_API_URL=s.site_api_url),
            facts={
                "site_api_url": s.site_api_url,
                "last_success_at": last_ok,
                "last_error": sync.get("error") if failing else None,
                "branches": await _count(session, Branch),
                "doctors": await _count(session, Doctor, Doctor.is_active.is_(True)),
                "services": await _count(session, Service, Service.is_active.is_(True)),
                "schedule": "02:00",
            },
            state="error" if failing else _age_state(last_ok, timedelta(hours=36)),
            test="site",
            docs="docs/02_ARXITEKTURA.md",
        )
    )
    return items


# --- safe tests -------------------------------------------------------------------------------


class TestFailedError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


async def _run(key: str) -> dict[str, Any]:
    s = get_settings()
    if key == "openai":
        client = httpx.AsyncClient(transport=_transport) if _transport else None
        return await openai_client.check_key(http_client=client)
    if key == "telegram":
        if not s.telegram_bot_token:
            raise TestFailedError("not_configured")
        bot = TelegramBot(transport=_transport)
        me = await bot.get_me()
        info = await bot.webhook_info()
        expected = f"{s.public_url.rstrip('/')}/api/integrations/telegram/webhook"
        return {
            "username": me.get("username"),
            "webhook_url": info.get("url") or None,
            "webhook_ok": info.get("url") == expected,
            "pending_updates": info.get("pending_update_count", 0),
            "last_error": info.get("last_error_message"),
        }
    if key == "instagram":
        if not (s.instagram_access_token and s.instagram_user_id):
            raise TestFailedError("not_configured")
        return await InstagramClient(transport=_transport).me()
    if key == "sms":
        if s.sms_provider != "eskiz" or not s.eskiz_email:
            raise TestFailedError("not_supported" if s.sms_provider else "not_configured")
        from app.integrations.sms.eskiz import EskizSms

        return {"provider": "eskiz", "balance": await EskizSms(transport=_transport).balance()}
    if key == "site":
        return await SiteClient(transport=_transport).check()
    raise TestFailedError("unknown_integration")


async def run_test(key: str) -> dict[str, Any]:
    """{"ok": True, "result": {...}} or {"ok": False, "error": code, "message": short text}.
    Error texts never contain secrets (the adapters strip URLs with tokens)."""
    try:
        return {"ok": True, "result": await _run(key)}
    except TestFailedError as exc:
        return {"ok": False, "error": exc.code, "message": exc.message}
    except openai_client.AiDisabledError:
        return {"ok": False, "error": "not_configured", "message": None}
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        return {"ok": False, "error": "auth_failed", "message": None}
    except openai.APIConnectionError:
        return {"ok": False, "error": "unreachable", "message": None}
    except openai.APIStatusError as exc:
        return {"ok": False, "error": f"http_{exc.status_code}", "message": None}
    except SendError as exc:
        return {"ok": False, "error": "provider_error", "message": str(exc)[:200]}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        return {"ok": False, "error": "auth_failed" if code in (401, 403) else f"http_{code}",
                "message": None}  # fmt: skip
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "error": "unreachable", "message": None}
