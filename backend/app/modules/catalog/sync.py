"""Synchronizes the catalog from the public radeski.uz API (branches, doctors, services, prices).

Site-owned fields (names, prices, activity) are overwritten; CRM-only fields are never touched.
Entries that disappear from the site are deactivated, not deleted (appointments reference them).
"""

import re
from collections import Counter
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.catalog.models import Branch, Doctor, Service, ServiceCategory
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


async def apply_site_data(
    session: AsyncSession,
    branches: list[dict[str, Any]],
    doctors: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> Counter[str]:
    counts: Counter[str] = Counter()

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
            )
            session.add(d)
            counts["doctors_created"] += 1
        d.name_uz, d.name_ru = item["name_uz"], item.get("name_ru") or item["name_uz"]
        d.title_uz, d.title_ru = item.get("role_uz"), item.get("role_ru")
        d.sort_order = int(item.get("sort_order") or 0)
        if not d.specialties:  # keep specialties edited in the CRM
            d.specialties = specialties_from_title(item.get("role_uz", ""))
    for sid, d in existing_d.items():
        if sid and sid not in seen and d.is_active:
            d.is_active = False
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
        price = item.get("price_value")
        s.price = int(price) if price else None
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
