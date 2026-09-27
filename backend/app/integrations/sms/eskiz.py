import httpx

from app.core.config import get_settings
from app.integrations.sms import SendError

BASE = "https://notify.eskiz.uz/api"
_token: str | None = None  # valid for 30 days; refreshed on 401


class EskizSms:
    name = "eskiz"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def _login(self, client: httpx.AsyncClient) -> str:
        global _token
        s = get_settings()
        resp = await client.post(
            f"{BASE}/auth/login", data={"email": s.eskiz_email, "password": s.eskiz_password}
        )
        if resp.status_code != 200:
            raise SendError(f"eskiz login: {resp.status_code} {resp.text[:200]}")
        _token = resp.json()["data"]["token"]
        return _token

    async def _post(self, client: httpx.AsyncClient, token: str, data: dict) -> httpx.Response:
        return await client.post(
            f"{BASE}/message/sms/send", data=data, headers={"Authorization": f"Bearer {token}"}
        )

    async def balance(self) -> float:
        """The account's SMS balance (read-only; admin "test" button)."""
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                token = _token or await self._login(client)
                resp = await client.get(
                    f"{BASE}/user/get-limit", headers={"Authorization": f"Bearer {token}"}
                )
                if resp.status_code == 401:  # token expired
                    token = await self._login(client)
                    resp = await client.get(
                        f"{BASE}/user/get-limit", headers={"Authorization": f"Bearer {token}"}
                    )
        except httpx.HTTPError as exc:
            raise SendError(f"eskiz: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SendError(f"eskiz: {resp.status_code}")
        data = resp.json()
        value = (data.get("data") or {}).get("balance", data.get("balance"))
        if value is None:
            raise SendError("eskiz: no balance in the answer")
        return float(value)

    async def send(self, phone: str, text: str, ref: str) -> str:
        s = get_settings()
        data = {"mobile_phone": phone.lstrip("+"), "message": text, "from": s.eskiz_from}
        if s.eskiz_callback_secret:  # delivery reports need the secret in the URL
            data["callback_url"] = (
                f"{s.public_url.rstrip('/')}/api/integrations/sms/eskiz/{s.eskiz_callback_secret}"
            )
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await self._post(client, _token or await self._login(client), data)
                if resp.status_code == 401:  # token expired
                    resp = await self._post(client, await self._login(client), data)
        except httpx.HTTPError as exc:
            raise SendError(f"eskiz: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SendError(f"eskiz: {resp.status_code} {resp.text[:200]}")
        return str(resp.json().get("id") or ref)
