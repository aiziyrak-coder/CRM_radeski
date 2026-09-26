from fastapi import FastAPI

from app.api import health
from app.core.config import get_settings
from app.modules.audit.router import router as audit_router
from app.modules.users.router import auth_router, users_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

for router in (health.router, auth_router, users_router, audit_router):
    app.include_router(router, prefix="/api")
