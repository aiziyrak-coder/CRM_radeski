"""Telegram Bot API (a bot, or a Telegram Business account connected to the bot)."""

from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.sms import SendError


class TelegramBot:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.token = get_settings().telegram_bot_token
        self.transport = transport

    async def call(self, method: str, payload: dict[str, Any]) -> Any:
        if not self.token:
            raise SendError("TELEGRAM_BOT_TOKEN is empty")
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{self.token}/{method}", json=payload
                )
        except httpx.HTTPError as exc:
            # the URL contains the token: never put the exception text into logs or the DB
            raise SendError(f"telegram: {type(exc).__name__}") from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not data.get("ok"):
            raise SendError(f"telegram: {data.get('description') or resp.status_code}")
        return data["result"]

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        business_connection_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = await self.call("sendMessage", payload)
        return str(result["message_id"])

    async def set_webhook(self, url: str, secret: str) -> None:
        await self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message", "business_message", "business_connection"],
            },
        )


def get_telegram() -> TelegramBot | None:
    return TelegramBot() if get_settings().telegram_bot_token else None
