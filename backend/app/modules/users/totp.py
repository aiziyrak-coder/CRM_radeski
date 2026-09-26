"""Second factor for admins and the owner (TZ 5: 2FA for privileged accounts, plan 0.2b).

Login with a password returns a short-lived challenge instead of tokens; the code from an
authenticator app (Google Authenticator, Aegis...) exchanges it for a session. The first time,
the challenge comes with a QR code to enrol the app.
"""

import base64
import io
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import segno

from app.core.config import get_settings
from app.modules.users.models import User

ISSUER = "Radeski CRM"
CHALLENGE_MINUTES = 5
_ALGORITHM = "HS256"


def required_for(user: User) -> bool:
    roles = {r.strip() for r in get_settings().totp_roles.split(",") if r.strip()}
    return user.role.value in roles


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning(user: User) -> tuple[str, str]:
    """(otpauth:// URI, QR code as an SVG data URI) for enrolling the authenticator app."""
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.username, issuer_name=ISSUER)
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2)
    return uri, "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def challenge_for(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "purpose": "totp",
        "iat": now,
        "exp": now + timedelta(minutes=CHALLENGE_MINUTES),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=_ALGORITHM)


def user_id_from(challenge: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(challenge, get_settings().jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != "totp":  # an access token is not a challenge
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


def verify(user: User, code: str) -> bool:
    """Accepts the current code (±30 s for clock drift); a code works only once."""
    if not user.totp_secret or not code.isdigit():
        return False
    totp = pyotp.TOTP(user.totp_secret)
    now = datetime.now(UTC)
    for offset in (0, -1, 1):
        at = now + timedelta(seconds=30 * offset)
        if totp.verify(code, for_time=at, valid_window=0):
            step = int(at.timestamp()) // 30
            if get_settings().totp_replay_guard and (user.totp_last_step or 0) >= step:
                return False
            user.totp_last_step = step
            return True
    return False
