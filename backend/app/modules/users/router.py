import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, client_ip, require_roles
from app.core.security import create_access_token, verify_password
from app.modules.audit import service as audit
from app.modules.users import service, totp
from app.modules.users.models import Role, User
from app.modules.users.schemas import (
    LoginIn,
    MeUpdate,
    PasswordChange,
    PasswordSet,
    TokenOut,
    TotpChallengeOut,
    TotpIn,
    UserCreate,
    UserOut,
    UserUpdate,
)

REFRESH_COOKIE = "crm_refresh"
REFRESH_COOKIE_PATH = "/api/auth"

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(require_roles(Role.ADMIN))]
)

AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _token_out(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role),
        expires_in=get_settings().access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


# --- auth -------------------------------------------------------------------------------------


@auth_router.post("/login")
async def login(
    body: LoginIn, request: Request, response: Response, session: SessionDep
) -> TokenOut | TotpChallengeOut:
    ip = client_ip(request) or "unknown"
    if await ratelimit.is_locked(body.username, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts")

    user = await service.authenticate(session, body.username, body.password)
    if user is None:
        await ratelimit.register_failure(body.username, ip)
        audit.record(session, "auth.login_failed", after={"username": body.username.lower()}, ip=ip)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    await ratelimit.reset(body.username, ip)
    if totp.required_for(user):
        out = TotpChallengeOut(challenge=totp.challenge_for(user))
        if not user.totp_enabled:
            # first login since 2FA became required: enrol the authenticator app
            user.totp_secret = totp.new_secret()
            out.setup, out.secret = True, user.totp_secret
            out.otpauth_uri, out.qr = totp.provisioning(user)
        await session.commit()
        return out
    raw = await service.start_session(session, user, ip, request.headers.get("user-agent"))
    audit.record(session, "auth.login", user_id=user.id, ip=ip)
    await session.commit()
    _set_refresh_cookie(response, raw)
    return _token_out(user)


@auth_router.post("/totp")
async def login_totp(
    body: TotpIn, request: Request, response: Response, session: SessionDep
) -> TokenOut:
    ip = client_ip(request) or "unknown"
    user_id = totp.user_id_from(body.challenge)
    user = await session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="challenge_expired")
    if await ratelimit.is_locked(user.username, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts")
    if not totp.verify(user, body.code.strip()):
        await ratelimit.register_failure(user.username, ip)
        audit.record(session, "auth.totp_failed", user_id=user.id, ip=ip)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_code")
    await ratelimit.reset(user.username, ip)
    if not user.totp_enabled:
        user.totp_enabled = True
        audit.record(session, "auth.totp_enrolled", user_id=user.id, ip=ip)
    raw = await service.start_session(session, user, ip, request.headers.get("user-agent"))
    audit.record(session, "auth.login", user_id=user.id, ip=ip, after={"totp": True})
    await session.commit()
    _set_refresh_cookie(response, raw)
    return _token_out(user)


@auth_router.post("/refresh")
async def refresh(
    request: Request, response: Response, session: SessionDep, cookie: RefreshCookie = None
) -> TokenOut:
    result = None
    if cookie:
        result = await service.rotate_session(
            session, cookie, client_ip(request), request.headers.get("user-agent")
        )
    await session.commit()
    if result is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="session_expired")
    user, new_raw = result
    _set_refresh_cookie(response, new_raw)
    return _token_out(user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: SessionDep, cookie: RefreshCookie = None
) -> None:
    if cookie:
        user_id = await service.revoke_session(session, cookie)
        if user_id:
            audit.record(session, "auth.logout", user_id=user_id, ip=client_ip(request))
        await session.commit()
    _clear_refresh_cookie(response)


@auth_router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@auth_router.patch("/me")
async def update_me(body: MeUpdate, user: CurrentUser, session: SessionDep) -> UserOut:
    user.language = body.language
    await session.commit()
    return UserOut.model_validate(user)


@auth_router.post("/change-password")
async def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
) -> TokenOut:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="wrong_password")
    await service.set_password(session, user, body.new_password)  # ends all other sessions
    raw = await service.start_session(
        session, user, client_ip(request), request.headers.get("user-agent")
    )
    audit.record(session, "auth.password_changed", user_id=user.id, ip=client_ip(request))
    await session.commit()
    _set_refresh_cookie(response, raw)
    return _token_out(user)


# --- user administration (admin only) ---------------------------------------------------------


async def _get_user_or_404(session: SessionDep, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_not_found")
    return user


@users_router.get("")
async def list_users(session: SessionDep) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.is_active.desc(), User.full_name))
    return [UserOut.model_validate(u) for u in users]


@users_router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, request: Request, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.create_user(session, body)
    except service.UsernameTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="username_taken") from None
    audit.record(
        session,
        "user.create",
        user_id=admin.id,
        entity="user",
        entity_id=user.id,
        after=service.snapshot(user),
        ip=client_ip(request),
    )
    await session.commit()
    return UserOut.model_validate(user)


@users_router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, session: SessionDep) -> UserOut:
    return UserOut.model_validate(await _get_user_or_404(session, user_id))


@users_router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> UserOut:
    user = await _get_user_or_404(session, user_id)
    if user.id == admin.id and (
        body.is_active is False or (body.role is not None and body.role != Role.ADMIN)
    ):
        # an admin locking themselves out would leave nobody able to manage users
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot_demote_self")

    if body.sip_extension and await session.scalar(
        select(User.id).where(User.sip_extension == body.sip_extension, User.id != user.id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="extension_taken")

    before = service.snapshot(user)
    service.apply_update(user, body)
    if body.is_active is False:
        await service.revoke_all_sessions(session, user.id)
    audit.record(
        session,
        "user.update",
        user_id=admin.id,
        entity="user",
        entity_id=user.id,
        before=before,
        after=service.snapshot(user),
        ip=client_ip(request),
    )
    await session.commit()
    return UserOut.model_validate(user)


@users_router.post("/{user_id}/totp-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_totp(
    user_id: uuid.UUID, request: Request, admin: AdminUser, session: SessionDep
) -> None:
    """Lost phone: the user enrols a new authenticator app at the next login."""
    user = await _get_user_or_404(session, user_id)
    user.totp_enabled, user.totp_secret, user.totp_last_step = False, None, None
    await service.revoke_all_sessions(session, user.id)
    audit.record(
        session, "user.totp_reset", user_id=admin.id, entity="user", entity_id=user.id,
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()


@users_router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordSet,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> None:
    user = await _get_user_or_404(session, user_id)
    await service.set_password(session, user, body.password)
    audit.record(
        session,
        "user.password_reset",
        user_id=admin.id,
        entity="user",
        entity_id=user.id,
        ip=client_ip(request),
    )
    await session.commit()
