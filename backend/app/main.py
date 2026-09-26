from fastapi import FastAPI

from app.api import health
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(health.router, prefix="/api")
