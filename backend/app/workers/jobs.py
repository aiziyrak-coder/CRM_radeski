"""Scheduled jobs (ARXITEKTURA 4.1). Each runs one async function in its own session."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
