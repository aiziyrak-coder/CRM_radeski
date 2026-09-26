"""Login brute-force protection backed by Redis."""

from redis.asyncio import Redis

from app.core.config import get_settings


def _key(username: str, ip: str) -> str:
    return f"login-fail:{username.lower()}:{ip}"


async def is_locked(username: str, ip: str) -> bool:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        fails = await redis.get(_key(username, ip))
        return fails is not None and int(fails) >= settings.login_max_attempts
    finally:
        await redis.aclose()


async def register_failure(username: str, ip: str) -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        key = _key(username, ip)
        await redis.incr(key)
        await redis.expire(key, settings.login_lock_minutes * 60)
    finally:
        await redis.aclose()


async def reset(username: str, ip: str) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.delete(_key(username, ip))
    finally:
        await redis.aclose()
