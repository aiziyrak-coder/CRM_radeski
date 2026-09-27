"""Instagram Direct via the Instagram Graph API (needs a reviewed Meta app, plan 5.3)."""

import hashlib
import hmac

import httpx

from app.core.config import get_settings
from app.integrations.sms import SendError


def valid_signature(body: bytes, header: str | None) -> bool:
    secret = get_settings().instagram_app_secret
    if not secret or not header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


class InstagramClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def send_message(self, recipient_id: str, text: str) -> str:
        s = get_settings()
        url = (
            f"https://graph.instagram.com/{s.instagram_graph_version}/"
            f"{s.instagram_user_id}/messages"
        )
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await client.post(
                    url,
                    json={"recipient": {"id": recipient_id}, "message": {"text": text}},
                    headers={"Authorization": f"Bearer {s.instagram_access_token}"},
                )
        except httpx.HTTPError as exc:
            raise SendError(f"instagram: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise SendError(f"instagram: {resp.status_code} {resp.text[:200]}")
        return str(resp.json().get("message_id", ""))

    async def me(self) -> dict[str, str]:
        """The account the token belongs to (read-only; admin "test" button)."""
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await client.get(
                    f"https://graph.instagram.com/{s.instagram_graph_version}/me",
                    params={"fields": "user_id,username"},
                    headers={"Authorization": f"Bearer {s.instagram_access_token}"},
                )
        except httpx.HTTPError as exc:
            raise SendError(f"instagram: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise SendError(f"instagram: {resp.status_code}")
        data = resp.json()
        return {"user_id": str(data.get("user_id") or data.get("id") or ""),
                "username": str(data.get("username") or "")}  # fmt: skip


def get_instagram() -> InstagramClient | None:
    s = get_settings()
    return InstagramClient() if s.instagram_access_token and s.instagram_user_id else None
