import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.catalog.models import Branch
from app.modules.users.models import User, UserSession
from app.modules.users.schemas import UserCreate, UserUpdate

# verified when the username doesn't exist, so response time doesn't reveal valid usernames
_DUMMY_HASH = hash_password("timing-equalizer")

REUSE_GRACE_SECONDS = 30

AUDITED_FIELDS = (
    "username", "full_name", "role", "language", "branch_id", "is_active", "sip_extension",
)  # fmt: skip


# columns that can't be cleared with an explicit null in a PATCH
_REQUIRED_FIELDS = ("full_name", "role", "language", "is_active")


class UsernameTakenError(Exception):
    pass


class BranchNotFoundError(Exception):
    pass


class ExtensionTakenError(Exception):
    pass


def snapshot(user: User) -> dict[str, Any]:
    """Audit-safe view of a user (never includes the password hash)."""
    data = {f: getattr(user, f) for f in AUDITED_FIELDS}
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}


def _now() -> datetime:
    return datetime.now(UTC)


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == username.lower()))


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    user = await get_by_username(session, username)
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password) or not user.is_active:
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = _now()
    return user


async def _check_branch(session: AsyncSession, branch_id: uuid.UUID | None) -> None:
    if branch_id is not None and await session.get(Branch, branch_id) is None:
        raise BranchNotFoundError(str(branch_id))


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    if await get_by_username(session, data.username):
        raise UsernameTakenError(data.username)
    await _check_branch(session, data.branch_id)
    user = User(
        username=data.username.lower(),
        full_name=data.full_name,
        role=data.role,
        language=data.language,
        branch_id=data.branch_id,
        password_hash=hash_password(data.password),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def apply_update(user: User, data: UserUpdate) -> None:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in _REQUIRED_FIELDS and value is None:
            continue
        setattr(user, field, value)


async def update_user(session: AsyncSession, user: User, data: UserUpdate) -> None:
    if "branch_id" in data.model_fields_set:
        await _check_branch(session, data.branch_id)
    apply_update(user, data)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        # two admins giving out the same softphone extension at once
        if "sip_extension" in str(exc.orig):
            raise ExtensionTakenError from None
        raise


async def set_password(session: AsyncSession, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    await revoke_all_sessions(session, user.id)


# --- sessions (refresh tokens) ---------------------------------------------------------------


async def start_session(
    session: AsyncSession, user: User, ip: str | None, user_agent: str | None
) -> str:
    raw, token_hash = new_refresh_token()
    now = _now()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash,
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(hours=get_settings().session_absolute_hours),
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return raw


async def rotate_session(
    session: AsyncSession, raw: str, ip: str | None, user_agent: str | None
) -> tuple[User, str] | None:
    """Exchanges a refresh token for a new one. Returns None if invalid, expired or idle."""
    settings = get_settings()
    current = await session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_refresh_token(raw))
    )
    if current is None:
        return None

    now = _now()
    if current.revoked_at is not None:
        # Two tabs refreshing at once legitimately race for a few seconds; anything later means
        # a rotated-out token was replayed -> likely stolen, so end every session of the user.
        if now - current.revoked_at > timedelta(seconds=REUSE_GRACE_SECONDS):
            await revoke_all_sessions(session, current.user_id)
        return None
    # last_used_at only moves on refresh (every access_token_minutes while the user is active),
    # so the server-side bound is idle + token lifetime; the UI logs out at exactly idle minutes.
    idle_limit = current.last_used_at + timedelta(
        minutes=settings.session_idle_minutes + settings.access_token_minutes
    )
    if now >= current.expires_at or now >= idle_limit:
        current.revoked_at = now
        return None

    user = await session.get(User, current.user_id)
    if user is None or not user.is_active:
        current.revoked_at = now
        return None

    current.revoked_at = now
    new_raw, new_hash = new_refresh_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=new_hash,
            created_at=now,
            last_used_at=now,
            expires_at=current.expires_at,  # absolute limit survives rotation
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return user, new_raw


async def revoke_session(session: AsyncSession, raw: str) -> uuid.UUID | None:
    current = await session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_refresh_token(raw))
    )
    if current is None or current.revoked_at is not None:
        return None
    current.revoked_at = _now()
    return current.user_id


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
