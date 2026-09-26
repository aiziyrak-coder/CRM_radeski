"""Brute-force protection for both login steps, backed by Redis.

Password step: failures are counted per (username, IP) and, with a higher threshold, per
username across all IPs. A correct password clears only the per-IP counter.

Authenticator step: failures are counted per user id, independently of the password counters,
so knowing the password doesn't allow unlimited code guessing by logging in again. Only a
correct code clears it. Each challenge token is also good for a limited number of codes.
"""

import uuid

from redis.asyncio import Redis

from app.core.config import get_settings


def _key(username: str, ip: str) -> str:
    return f"login-fail:{username.lower()}:{ip}"


def _user_key(username: str) -> str:
    return f"login-fail-user:{username.lower()}"


def _totp_key(user_id: uuid.UUID) -> str:
    return f"totp-fail:{user_id}"


def _challenge_key(jti: str) -> str:
    return f"totp-challenge:{jti}"


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


async def _count(redis: Redis, key: str) -> int:
    value = await redis.get(key)
    return int(value) if value is not None else 0


async def _incr(redis: Redis, key: str, ttl_seconds: int) -> int:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        count, _ = await pipe.execute()
    return int(count)


# --- password step -----------------------------------------------------------------------------


async def is_locked(username: str, ip: str) -> bool:
    settings = get_settings()
    redis = _redis()
    try:
        return (
            await _count(redis, _key(username, ip)) >= settings.login_max_attempts
            or await _count(redis, _user_key(username)) >= settings.login_max_attempts_per_user
        )
    finally:
        await redis.aclose()


async def register_failure(username: str, ip: str) -> None:
    ttl = get_settings().login_lock_minutes * 60
    redis = _redis()
    try:
        await _incr(redis, _key(username, ip), ttl)
        await _incr(redis, _user_key(username), ttl)
    finally:
        await redis.aclose()


async def reset(username: str, ip: str) -> None:
    """After a correct password. The per-username counter only expires (an attacker spreading
    guesses over many IPs must not be able to clear it with one legitimate login)."""
    redis = _redis()
    try:
        await redis.delete(_key(username, ip))
    finally:
        await redis.aclose()


# --- authenticator step ------------------------------------------------------------------------


async def totp_locked(user_id: uuid.UUID) -> bool:
    redis = _redis()
    try:
        return await _count(redis, _totp_key(user_id)) >= get_settings().totp_max_attempts
    finally:
        await redis.aclose()


async def register_totp_failure(user_id: uuid.UUID) -> bool:
    """Counts a wrong code; returns True if the user's second step is now locked."""
    settings = get_settings()
    redis = _redis()
    try:
        count = await _incr(redis, _totp_key(user_id), settings.totp_lock_minutes * 60)
        return count >= settings.totp_max_attempts
    finally:
        await redis.aclose()


async def reset_totp(user_id: uuid.UUID) -> None:
    redis = _redis()
    try:
        await redis.delete(_totp_key(user_id))
    finally:
        await redis.aclose()


async def use_challenge(jti: str, ttl_seconds: int) -> bool:
    """Counts one code submitted with a challenge; False once the challenge is used up."""
    redis = _redis()
    try:
        count = await _incr(redis, _challenge_key(jti), ttl_seconds)
        return count <= get_settings().totp_challenge_max_attempts
    finally:
        await redis.aclose()


async def burn_challenge(jti: str, ttl_seconds: int) -> None:
    """A challenge that produced a session can't be used again."""
    redis = _redis()
    try:
        await redis.set(_challenge_key(jti), 1_000_000, ex=ttl_seconds)
    finally:
        await redis.aclose()
