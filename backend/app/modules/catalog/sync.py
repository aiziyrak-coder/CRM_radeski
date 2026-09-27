"""Synchronizes the catalog from the public radeski.uz API (branches, doctors, services, prices).

Site-owned fields (names, prices, activity) are overwritten; CRM-only fields are never touched.
Entries that disappear from the site are deactivated, not deleted (appointments reference them).
A doctor the sync deactivated comes back when they reappear on the site; a doctor an admin
deactivated stays off. A suspicious snapshot (an empty list, or one that shrank by more than
catalog_sync_max_shrink) aborts the whole sync instead of deactivating half the clinic.
"""

import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.catalog.models import (
    Branch,
    CatalogSyncRun,
    Doctor,
    Service,
    ServiceCategory,
    SyncStatus,
)
from app.modules.diagnoses.categories import Specialty

# site service category -> specialty and default device (TZ 4.2)
CATEGORY_DEFAULTS: dict[str, tuple[Specialty, str | None]] = {
    "apparatnaya-kosmetologiya": (Specialty.COSMETOLOGIST, None),
    "clinika-patologii-nogtej": (Specialty.PODOLOGIST, None),
    "dermatologiya": (Specialty.DERMATOLOGIST, None),
    "dermatoonkologiya": (Specialty.ONCODERMATOLOGIST, None),
    "dermatopatologiya": (Specialty.ONCODERMATOLOGIST, None),
    "hirurgicheskaya-dermatologiya": (Specialty.ONCODERMATOLOGIST, None),
    "in-ekcionnaya-kosmetologiya": (Specialty.COSMETOLOGIST, None),
    "lazernaya-epilyaciya": (Specialty.COSMETOLOGIST, "laser_epilation"),
    "trihologiya-centr-lechenie-volos": (Specialty.TRICHOLOGIST, None),
    "trixoskopiya": (Specialty.TRICHOLOGIST, None),
}

# words in a doctor's title (uz) -> specialty
_TITLE_SPECIALTIES: tuple[tuple[str, Specialty], ...] = (
    (r"trixolog|трихолог", Specialty.TRICHOLOGIST),
    (r"podolog", Specialty.PODOLOGIST),
    (r"onkolog|dermatoxirurg", Specialty.ONCODERMATOLOGIST),
    (r"kosmetolog", Specialty.COSMETOLOGIST),
    # "Onkodermatolog" / "Dermatoxirurg" alone don't make someone a general dermatologist
    (r"\bdermato(?!onkolog|xirurg)|venerolog", Specialty.DERMATOLOGIST),
)

_CONSULTATION = re.compile(r"ko'rigi|konsultatsiya|konsultatsiyasi|консультац|приём|прием", re.I)


def specialties_from_title(title: str) -> list[Specialty]:
    found = [s for pattern, s in _TITLE_SPECIALTIES if re.search(pattern, title or "", re.I)]
    return sorted(set(found), key=list(Specialty).index)


def _is_foreign_branch(item: dict[str, Any]) -> bool:
    # the site also lists a partner clinic in Belgium; it is not part of this CRM
    text = f"{item.get('address_uz', '')} {item.get('name_uz', '')}"
    return "Belgiya" in text or (item.get("phone") or "").startswith("+32")


def parse_price(value: Any) -> int | None:
    """Price from the site: 150000, "150000", "150 000", "150 000.00" -> 150000. 0 is a real price
    (a free consultation); anything unreadable is None instead of stopping the whole sync."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    digits = str(value).replace(chr(0xA0), "").replace(" ", "").replace(",", ".")
    try:
        return int(float(digits))
    except ValueError:
        return None


class SyncAbortedError(Exception):
    """The site returned a list that looks broken; nothing was changed."""

    def __init__(self, entity: str, fetched: int, active: int) -> None:
        super().__init__(f"{entity}: site returned {fetched}, {active} active in the CRM")
        self.entity, self.fetched, self.active = entity, fetched, active


async def _check_not_shrunk(session: AsyncSession, model: Any, entity: str, ids: set[str]) -> None:
    active = (
        await session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.site_id.is_not(None), model.is_active.is_(True))
        )
        or 0
    )
    max_shrink = get_settings().catalog_sync_max_shrink
    if not ids or (active and len(ids) < active * (1 - max_shrink)):
        raise SyncAbortedError(entity, len(ids), active)


async def apply_site_data(
    session: AsyncSession,
    branches: list[dict[str, Any]],
    doctors: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> Counter[str]:
    counts: Counter[str] = Counter()

    # validate every list before touching anything
    await _check_not_shrunk(
        session,
        Branch,
        "branches",
        {str(b["id"]) for b in branches if not _is_foreign_branch(b)},
    )
    await _check_not_shrunk(session, Doctor, "doctors", {str(d["id"]) for d in doctors})
    await _check_not_shrunk(session, Service, "prices", {str(p["id"]) for p in prices})

    # --- branches ---
    existing_b = {b.site_id: b for b in await session.scalars(select(Branch))}
    seen: set[str] = set()
    for item in branches:
        if _is_foreign_branch(item):
            counts["branches_skipped_foreign"] += 1
            continue
        sid = str(item["id"])
        seen.add(sid)
        b = existing_b.get(sid) or Branch(site_id=sid)
        if b.id is None:
            session.add(b)
            counts["branches_created"] += 1
        b.name_uz, b.name_ru = item["name_uz"], item.get("name_ru") or item["name_uz"]
        b.address_uz, b.phone = item.get("address_uz"), item.get("phone")
        b.is_main = bool(item.get("is_main"))
        b.is_active = bool(item.get("is_active", True))
        b.sort_order = int(item.get("sort_order") or 0)
    for sid, b in existing_b.items():
        if sid and sid not in seen and b.is_active:
            b.is_active = False
            counts["branches_deactivated"] += 1

    # --- doctors ---
    existing_d = {d.site_id: d for d in await session.scalars(select(Doctor))}
    seen = set()
    for item in doctors:
        sid = str(item["id"])
        seen.add(sid)
        d = existing_d.get(sid)
        if d is None:
            d = Doctor(
                site_id=sid,
                specialties=specialties_from_title(item.get("role_uz", "")),
                is_active=True,
                deactivated_by_sync=False,
            )
            session.add(d)
            counts["doctors_created"] += 1
        d.name_uz, d.name_ru = item["name_uz"], item.get("name_ru") or item["name_uz"]
        d.title_uz, d.title_ru = item.get("role_uz"), item.get("role_ru")
        d.sort_order = int(item.get("sort_order") or 0)
        if not d.specialties:  # keep specialties edited in the CRM
            d.specialties = specialties_from_title(item.get("role_uz", ""))
        if not d.is_active and d.deactivated_by_sync:
            d.is_active, d.deactivated_by_sync = True, False
            counts["doctors_reactivated"] += 1
    for sid, d in existing_d.items():
        if sid and sid not in seen and d.is_active:
            d.is_active, d.deactivated_by_sync = False, True
            counts["doctors_deactivated"] += 1

    # --- service categories ---
    existing_c = {c.site_id: c for c in await session.scalars(select(ServiceCategory))}
    for item in categories:
        sid = str(item["id"])
        c = existing_c.get(sid)
        if c is None:
            c = ServiceCategory(site_id=sid, specialty=CATEGORY_DEFAULTS.get(sid, (None,))[0])
            session.add(c)
            existing_c[sid] = c
            counts["categories_created"] += 1
        c.name_uz = item.get("title_uz") or sid
        c.name_ru = item.get("title_ru") or c.name_uz
    await session.flush()

    # --- services (price list) ---
    existing_s = {s.site_id: s for s in await session.scalars(select(Service))}
    seen = set()
    for item in prices:
        sid = str(item["id"])
        seen.add(sid)
        cat_sid = item.get("category_id")
        s = existing_s.get(sid)
        if s is None:
            default_device = CATEGORY_DEFAULTS.get(cat_sid, (None, None))[1]
            s = Service(
                site_id=sid,
                device_type=default_device,
                is_consultation=bool(_CONSULTATION.search(item.get("name_uz", ""))),
                duration_min=30,
            )
            session.add(s)
            counts["services_created"] += 1
        s.name_uz = item["name_uz"]
        s.name_ru = item.get("name_ru") or item["name_uz"]
        s.price = parse_price(item.get("price_value"))
        s.category_id = existing_c[cat_sid].id if cat_sid in existing_c else None
        s.is_active = True
    for sid, s in existing_s.items():
        if sid and sid not in seen and s.is_active:
            s.is_active = False
            counts["services_deactivated"] += 1

    await session.flush()
    return counts


async def fetch_site_data(base_url: str | None = None) -> dict[str, list[dict[str, Any]]]:
    base = (base_url or get_settings().site_api_url).rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        out = {}
        for name in ("branches", "doctors", "services", "prices"):
            resp = await client.get(f"{base}/api/{name}")
            resp.raise_for_status()
            out[name] = resp.json()
        return out


async def sync_from_site(session: AsyncSession) -> Counter[str]:
    data = await fetch_site_data()
    return await apply_site_data(
        session, data["branches"], data["doctors"], data["services"], data["prices"]
    )


async def run_and_record(
    session: AsyncSession, *, trigger: str, user_id: uuid.UUID | None = None
) -> CatalogSyncRun:
    """Runs the sync and stores its outcome (the settings page shows the last one).

    An aborted or failed sync is rolled back; only its run row is kept. The caller commits."""
    started = datetime.now(UTC)
    status, counts, error = SyncStatus.OK, None, None
    try:
        counts = dict(await sync_from_site(session))
    except SyncAbortedError as exc:
        await session.rollback()
        status = SyncStatus.ABORTED
        counts = {"entity": exc.entity, "fetched": exc.fetched, "active": exc.active}
    except (httpx.HTTPError, ValueError, KeyError) as exc:  # site unreachable / bad response
        await session.rollback()
        status, error = SyncStatus.FAILED, f"{type(exc).__name__}: {exc}"[:500]
    run = CatalogSyncRun(
        started_at=started,
        finished_at=datetime.now(UTC),
        trigger=trigger,
        user_id=user_id,
        status=status,
        counts=counts,
        error=error,
    )
    session.add(run)
    await session.flush()
    return run
