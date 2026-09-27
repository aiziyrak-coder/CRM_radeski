"""When a background integration job last ran and last succeeded (site polling, catalog sync).

Kept in Redis (one small hash per job, no expiry): it is operational state for the admin's
integrations page, not business data. Jobs call `record` (sync Redis client, Celery tasks are
sync); the page reads with `read`."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import get_settings

log = logging.getLogger(__name__)
JOBS = ("site_poll", "catalog_sync")


def _key(name: str) -> str:
    return f"hb:{name}"


def record(name: str, *, ok: bool, error: str | None = None, detail: Any = None) -> None:
    """Never raises: bookkeeping must not fail the job it describes."""
    now = datetime.now(UTC).isoformat()
    fields = {"last_run": now}
    if ok:
        fields |= {"last_ok": now, "detail": json.dumps(detail or {}, default=str)}
    else:
        fields |= {"last_error_at": now, "error": (error or "error")[:200]}
    try:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            redis.hset(_key(name), mapping=fields)
        finally:
            redis.close()
    except Exception:
        log.exception("could not record heartbeat %s", name)


async def read(name: str) -> dict[str, Any]:
    redis = AsyncRedis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        raw = await redis.hgetall(_key(name))
    except Exception:
        log.exception("could not read heartbeat %s", name)
        return {}
    finally:
        await redis.aclose()
    out: dict[str, Any] = {k: raw.get(k) for k in ("last_run", "last_ok", "last_error_at", "error")}
    try:
        out["detail"] = json.loads(raw["detail"]) if raw.get("detail") else None
    except ValueError:
        out["detail"] = None
    # the last run failed when its error is newer than its last success
    out["failing"] = bool(out["last_error_at"]) and (out["last_ok"] or "") < out["last_error_at"]
    return out
