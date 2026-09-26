from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.modules.ai.rules  # noqa: F401  - operator review of AI suggestions
import app.modules.tasks.rules  # noqa: F401  - registers the task rules on domain events
from app.api import health
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.ai.router import router as ai_router
from app.modules.audit.router import router as audit_router
from app.modules.campaigns.router import router as campaigns_router
from app.modules.catalog.router import router as catalog_router
from app.modules.diagnoses.router import router as diagnoses_router
from app.modules.leads.router import router as leads_router
from app.modules.leads.router import webhook_router
from app.modules.patients.router import router as patients_router
from app.modules.reports.router import router as reports_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.scripts.router import router as scripts_router
from app.modules.scripts.router import seed_if_empty
from app.modules.tasks.router import router as tasks_router
from app.modules.telephony.router import router as telephony_router
from app.modules.timeline.router import router as timeline_router
from app.modules.users.router import auth_router, users_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.environment != "test":
        async with SessionLocal() as session:
            await seed_if_empty(session)
    yield


app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

for router in (
    health.router,
    auth_router,
    users_router,
    audit_router,
    patients_router,
    diagnoses_router,
    catalog_router,
    scheduling_router,
    tasks_router,
    leads_router,
    webhook_router,
    scripts_router,
    campaigns_router,
    reports_router,
    timeline_router,
    telephony_router,
    ai_router,
):
    app.include_router(router, prefix="/api")
