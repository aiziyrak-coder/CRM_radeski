from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    """Process is up. Used by Docker healthcheck and uptime monitors."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(response: Response) -> dict[str, str]:
    """Dependencies (PostgreSQL, Redis) are reachable."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as unhealthy
        checks["db"] = f"error: {type(exc).__name__}"

    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"
    finally:
        await redis.aclose()

    if any(v != "ok" for v in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
