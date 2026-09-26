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
    from app.modules.tasks.rules import generate_confirmations

    return _run(generate_confirmations)


@celery_app.task(name="jobs.lost_leads")
def lost_leads() -> int:
    from app.modules.tasks.rules import generate_lost_leads

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
    from app.modules.catalog.sync import sync_from_site

    return dict(_run(sync_from_site))


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

    return _run(intake)


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
    from app.modules.messaging.service import deliver, due_messages

    async def run(session):
        ids = await due_messages(session)
        for message_id in ids:
            await deliver(session, message_id)
        return len(ids)

    return _run(run)


@celery_app.task(name="jobs.reminders")
def reminders() -> int:
    from app.modules.messaging.rules import send_reminders

    return _run(send_reminders)
