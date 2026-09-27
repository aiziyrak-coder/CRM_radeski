"""radeski.uz admin API client — fallback polling for form submissions (ARXITEKTURA 4.5).

The primary path is the signed webhook; polling only runs when admin credentials are configured.
"""

from typing import Any

import httpx

from app.core.config import get_settings


class SiteClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        settings = get_settings()
        self.base = settings.site_api_url.rstrip("/")
        self.username = settings.site_admin_username
        self.password = settings.site_admin_password
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password)

    async def _token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            f"{self.base}/api/admin/login",
            json={"username": self.username, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token") or data["token"]

    async def check(self) -> dict[str, Any]:
        """Reads the public branch list (the catalog sync's first request) and, when admin
        credentials are set, logs in as the fallback polling does. Changes nothing."""
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            resp = await client.get(f"{self.base}/api/branches")
            resp.raise_for_status()
            branches = resp.json()
            admin = None
            if self.enabled:
                await self._token(client)
                admin = True
        return {"branches": len(branches) if isinstance(branches, list) else None, "admin": admin}

    async def new_appointments(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            token = await self._token(client)
            resp = await client.get(
                f"{self.base}/api/admin/appointments",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", [])
            return [a for a in items if a.get("status") in (None, "new", "pending")]
