"""Scheduled jobs (ARXITEKTURA 4.1). Each runs one async function in its own session."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.ai.rules  # noqa: F401
import app.modules.messaging.rules  # noqa: F401
import app.modules.tasks.rules  # noqa: F401  - event handlers must be registered in workers too
from app.core.db import SessionLocal
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _run(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    async def wrapper() -> Any:
        async with SessionLocal() as session:
            result = await fn(session)
            await session.commit()
            return result

    return asyncio.run(wrapper())


@celery_app.task(name="jobs.confirmations")
def confirmations() -> int:
    from app.modules.tasks.rules import close_already_booked, generate_confirmations

    _run(close_already_booked)  # before the morning queue is worked
    return _run(generate_confirmations)


@celery_app.task(name="jobs.lost_leads")
def lost_leads() -> int:
    from app.modules.tasks.rules import close_already_booked, generate_lost_leads

    _run(close_already_booked)  # hourly: calls that came due since the morning
    return _run(generate_lost_leads)


@celery_app.task(name="jobs.reactivation")
def reactivation() -> int:
    from app.modules.tasks.rules import generate_reactivation

    return _run(generate_reactivation)


@celery_app.task(name="jobs.campaigns")
def campaigns() -> int:
    from app.modules.campaigns.service import generate_all

    return _run(generate_all)


@celery_app.task(name="jobs.sync_catalog")
def sync_catalog() -> dict[str, int]:
    from app.modules.catalog.models import SyncStatus
    from app.modules.catalog.sync import run_and_record
    from app.modules.integrations_status import heartbeat

    async def sync(session: AsyncSession) -> dict[str, int]:
        run = await run_and_record(session, trigger="auto")  # outcome shown in settings
        if run.status is not SyncStatus.OK:  # empty/partial list or no site: keep ours
            log.warning("catalog sync %s, nothing changed: %s", run.status, run.counts or run.error)
            error = "sync_aborted" if run.status is SyncStatus.ABORTED else (run.error or "failed")
            heartbeat.record("catalog_sync", ok=False, error=error)
            return {run.status.value: 1}
        heartbeat.record("catalog_sync", ok=True, detail=dict(run.counts or {}))
        return dict(run.counts or {})

    return dict(_run(sync))


@celery_app.task(name="jobs.sync_diagnoses")
def sync_diagnoses() -> dict[str, int]:
    from app.modules.diagnoses.service import sync

    return dict(_run(sync))


@celery_app.task(name="jobs.poll_site")
def poll_site() -> int:
    from app.integrations.site import SiteClient
    from app.modules.leads.router import SiteAppointmentIn, intake_site_appointment

    client = SiteClient()
    if not client.enabled:
        return 0

    async def intake(session: AsyncSession) -> int:
        created = 0
        for item in await client.new_appointments():
            try:
                body = SiteAppointmentIn.model_validate(item)
            except ValueError:
                log.warning("skipping malformed site appointment %s", item.get("id"))
                continue
            _, is_new = await intake_site_appointment(session, body)
            created += is_new
        return created

    from app.modules.integrations_status import heartbeat

    try:
        created = _run(intake)
    except Exception as exc:  # the admin's integrations page shows the failing polling
        heartbeat.record("site_poll", ok=False, error=type(exc).__name__)
        raise
    heartbeat.record("site_poll", ok=True, detail={"created": created})
    return created


@celery_app.task(name="jobs.process_recording")
def process_recording(call_id: str) -> str | None:
    """Queued by the PBX event endpoint for every answered call."""
    import uuid

    from app.modules.telephony.service import process_recording as convert

    status = _run(lambda session: convert(session, uuid.UUID(call_id)))
    if status and status.value == "ready":
        analyze_call.delay(call_id)
    return status.value if status else None


@celery_app.task(name="jobs.retry_recordings")
def retry_recordings() -> int:
    from app.modules.telephony.service import retry_recordings as run

    return _run(run)


@celery_app.task(name="jobs.close_stale_calls")
def close_stale_calls() -> int:
    """Every 10 min: calls whose hangup report never arrived (CRM down at that moment)."""
    from app.modules.telephony.service import close_stale_calls as run

    return _run(run)


@celery_app.task(name="jobs.analyze_call")
def analyze_call(call_id: str) -> str | None:
    """Transcript + QA analysis; a no-op while OPENAI_API_KEY is empty."""
    import uuid

    from app.modules.ai.service import analyze_call as run

    status = _run(lambda session: run(session, uuid.UUID(call_id)))
    return status.value if status else None


@celery_app.task(name="jobs.retry_analyses")
def retry_analyses() -> int:
    """Every 30 min: failed/stuck analyses and the backlog once the API key is added."""
    from app.integrations.openai_client import enabled
    from app.modules.ai.service import pending_calls

    if not enabled():
        return 0
    ids = _run(pending_calls)
    for call_id in ids:
        analyze_call.delay(str(call_id))
    return len(ids)


@celery_app.task(name="jobs.ai_diagnoses")
def ai_diagnoses() -> dict[str, int]:
    from app.modules.diagnoses.service import run_ai_suggestions

    return dict(_run(run_ai_suggestions) or {})


@celery_app.task(name="jobs.weekly_digest")
def weekly_digest() -> str:
    from app.modules.ai.qa import make_digest

    return str(_run(lambda session: make_digest(session)).id)


@celery_app.task(name="jobs.deliver_message")
def deliver_message(message_id: str) -> str | None:
    import uuid

    from app.modules.messaging.service import deliver

    status = _run(lambda session: deliver(session, uuid.UUID(message_id)))
    return status.value if status else None


@celery_app.task(name="jobs.deliver_due")
def deliver_due() -> int:
    """Every minute: queued messages whose time has come (reminders after quiet hours, retries)."""
    from app.modules.messaging.service import deliver_due as run

    return _run(run)


@celery_app.task(name="jobs.reminders")
def reminders() -> int:
    from app.modules.messaging.rules import send_reminders

    return _run(send_reminders)
