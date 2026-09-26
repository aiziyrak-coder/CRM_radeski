import httpx

from app.core.config import get_settings
from app.integrations.sms import SendError


class PlaymobileSms:
    name = "playmobile"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def send(self, phone: str, text: str, ref: str) -> str:
        s = get_settings()
        message_id = ref.replace("-", "")[:40]
        body = {
            "messages": [
                {
                    "recipient": phone.lstrip("+"),
                    "message-id": message_id,
                    "sms": {"originator": s.playmobile_originator, "content": {"text": text}},
                }
            ]
        }
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await client.post(
                    s.playmobile_url, json=body, auth=(s.playmobile_login, s.playmobile_password)
                )
        except httpx.HTTPError as exc:
            raise SendError(f"playmobile: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SendError(f"playmobile: {resp.status_code} {resp.text[:200]}")
        return message_id
