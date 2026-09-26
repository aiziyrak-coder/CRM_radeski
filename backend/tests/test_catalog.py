import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.catalog import sync as sync_module
from app.modules.catalog.models import Branch, Doctor, Service
from app.modules.catalog.sync import SyncAbortedError, apply_site_data, specialties_from_title
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


async def _sync(doctors: list[dict] | None = None, prices: list[dict] | None = None) -> dict:
    async with SessionLocal() as s:
        counts = await apply_site_data(
            s,
            site("branches"),
            site("doctors") if doctors is None else doctors,
            site("services"),
            site("prices") if prices is None else prices,
        )
        await s.commit()
        return counts


async def _active_doctor(site_id: str) -> bool:
    async with SessionLocal() as s:
        return await s.scalar(select(Doctor.is_active).where(Doctor.site_id == site_id))


async def test_doctor_back_on_the_site_is_reactivated_unless_an_admin_turned_them_off(
    client: AsyncClient,
) -> None:
    doctors = site("doctors")
    await _sync()
    gone, other = str(doctors[-1]["id"]), str(doctors[0]["id"])

    await _sync(doctors=doctors[:-1])
    assert await _active_doctor(gone) is False
    again = await _sync()
    assert again["doctors_reactivated"] == 1 and await _active_doctor(gone) is True

    # an admin's deactivation sticks through syncs
    await make_user("admin", Role.ADMIN)
    admin = bearer(await login(client, "admin"))
    async with SessionLocal() as s:
        other_id = await s.scalar(select(Doctor.id).where(Doctor.site_id == other))
    resp = await client.patch(
        f"/api/catalog/doctors/{other_id}", json={"is_active": False}, headers=admin
    )
    assert resp.status_code == 200
    await _sync()
    assert await _active_doctor(other) is False


async def test_suspicious_site_snapshot_aborts_the_sync() -> None:
    await _sync()
    doctors, prices = site("doctors"), site("prices")

    for bad in ({"doctors": []}, {"doctors": doctors[:3]}, {"prices": prices[:100]}):
        with pytest.raises(SyncAbortedError):
            await _sync(**bad)

    async with SessionLocal() as s:
        inactive_doctors = await s.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_active.is_(False))
        )
        inactive_services = await s.scalar(
            select(func.count()).select_from(Service).where(Service.is_active.is_(False))
        )
    assert inactive_doctors == 0 and inactive_services == 0


async def test_sync_endpoint_reports_an_aborted_sync(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _sync()

    async def empty_site() -> dict:
        return {
            "branches": site("branches"),
            "doctors": [],
            "services": site("services"),
            "prices": site("prices"),
        }

    monkeypatch.setattr(sync_module, "fetch_site_data", empty_site)
    await make_user("admin", Role.ADMIN)
    admin = bearer(await login(client, "admin"))
    resp = await client.post("/api/catalog/sync", headers=admin)
    assert resp.status_code == 409 and resp.json()["detail"] == "sync_aborted"
    assert await _active_doctor(str(site("doctors")[0]["id"])) is True


async def test_catalog_patch_ignores_nulls_and_links_a_user_once(client: AsyncClient) -> None:
    await _sync()
    await make_user("admin", Role.ADMIN)
    admin = bearer(await login(client, "admin"))
    doc_user = await make_user("doc1", Role.DOCTOR)
    async with SessionLocal() as s:
        first, second = list(await s.scalars(select(Doctor.id).limit(2)))
        service_id = await s.scalar(select(Service.id).limit(1))

    resp = await client.patch(
        f"/api/catalog/services/{service_id}",
        json={"duration_min": None, "is_consultation": None, "requires_consultation": None},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.json()["duration_min"] == 30
    resp = await client.patch(
        f"/api/catalog/doctors/{first}",
        json={"specialties": None, "is_active": None, "user_id": str(doc_user.id)},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is True

    taken = await client.patch(
        f"/api/catalog/doctors/{second}", json={"user_id": str(doc_user.id)}, headers=admin
    )
    assert taken.status_code == 409 and taken.json()["detail"] == "user_already_linked"
    unknown = await client.patch(
        f"/api/catalog/doctors/{second}", json={"user_id": str(uuid.uuid4())}, headers=admin
    )
    assert unknown.status_code == 404
