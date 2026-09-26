import json
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.catalog.models import Branch, Doctor, Service
from app.modules.catalog.sync import apply_site_data, specialties_from_title
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user

FIXTURES = Path(__file__).parent / "fixtures"


def site(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"site_{name}.json").read_text(encoding="utf-8"))


def test_specialties_from_doctor_titles() -> None:
    assert specialties_from_title("Dermatolog, Trixolog (Soch kasalliklari mutaxassisi)") == [
        "dermatologist",
        "trichologist",
    ]
    assert specialties_from_title("Dermatoxirurg, Onkodermatolog") == ["oncodermatologist"]
    assert "podologist" in specialties_from_title("Shifokor-dermatovenerolog, podolog")


async def test_sync_from_site_snapshot() -> None:
    async with SessionLocal() as s:
        counts = await apply_site_data(
            s, site("branches"), site("doctors"), site("services"), site("prices")
        )
        await s.commit()

    assert counts["branches_created"] == 2  # Fergana + Kokand
    assert counts["branches_skipped_foreign"] == 1  # the Belgian partner clinic
    assert counts["doctors_created"] == 11
    assert counts["services_created"] == 806

    async with SessionLocal() as s:
        laser = await s.scalar(
            select(func.count())
            .select_from(Service)
            .where(Service.device_type == "laser_epilation")
        )
        assert laser == 25
        consult = await s.scalar(
            select(func.count()).select_from(Service).where(Service.is_consultation.is_(True))
        )
        assert consult >= 5

        # CRM-edited fields survive the next sync; removed site entries are deactivated
        service = await s.scalar(select(Service).limit(1))
        service.duration_min = 90
        await s.commit()
        service_id = service.id

    async with SessionLocal() as s:
        again = await apply_site_data(
            s, site("branches"), site("doctors")[:-1], site("services"), site("prices")
        )
        await s.commit()
        assert again["doctors_deactivated"] == 1 and again.get("services_created", 0) == 0
        assert (await s.get(Service, service_id)).duration_min == 90
        assert await s.scalar(select(func.count()).select_from(Branch)) == 2
        assert (
            await s.scalar(
                select(func.count()).select_from(Doctor).where(Doctor.is_active.is_(False))
            )
            == 1
        )


async def test_only_admin_edits_catalog(client: AsyncClient) -> None:
    async with SessionLocal() as s:
        await apply_site_data(
            s, site("branches"), site("doctors"), site("services"), site("prices")
        )
        await s.commit()
        service_id = str(await s.scalar(select(Service.id).limit(1)))

    await make_user("op1", Role.OPERATOR)
    await make_user("admin", Role.ADMIN)
    op = bearer(await login(client, "op1"))
    admin = bearer(await login(client, "admin"))

    body = {"duration_min": 45, "min_interval_days": 30}
    assert (
        await client.patch(f"/api/catalog/services/{service_id}", json=body, headers=op)
    ).status_code == 403
    resp = await client.patch(f"/api/catalog/services/{service_id}", json=body, headers=admin)
    assert resp.status_code == 200 and resp.json()["duration_min"] == 45

    found = await client.get("/api/catalog/services", params={"q": "epilyatsiya"}, headers=op)
    assert found.status_code == 200
