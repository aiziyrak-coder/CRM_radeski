import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.diagnoses.categories import CATEGORIES, CATEGORY_BY_CODE, suggest_category
from app.modules.patients.models import Patient, PatientCondition, PatientKind
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Андроген алопеция 3-4-даража", "alopecia_androgenic"),
        ("L63-Гнездная алопеция", "alopecia_areata"),
        ("Ўчокли алопеция", "alopecia_areata"),
        ("Диффуз аллопеция", "alopecia_diffuse"),  # common typo
        ("Соч оқариши", "hair_other"),
        ("Витилиго тарқоқ тури", "vitiligo"),
        ("Псевдовитилиго", "pigmentation"),
        ("Парапсориаз L41", "parapsoriasis"),
        ("распр. псориаз", "psoriasis"),
        ("Пуштиранг хуснбузар", "rosacea"),  # "pink acne" is rosacea, not acne
        ("Вульгар хуснбузар", "acne"),
        ("L70.0 Вульгарные угри", "acne"),
        ("Себорейный кератоз", "benign_tumor"),  # not seborrheic dermatitis
        ("L21.0-Себорея головы", "seborrheic_dermatitis"),
        ("Себорейный дерматит, псориаз", "seborrheic_dermatitis"),  # first diagnosis wins
        ("Витилиго. Кантактли дерматит", "vitiligo"),
        ("Простой лихен Видаля", "atopic_dermatitis"),
        ("Вирусные бородавки", "warts_papilloma"),
        ("Онихомикоз?", "nails_feet"),  # nail fungus -> podologist
        ("Микоз гладкой кожи", "fungal"),
        ("БКР?", "skin_cancer_suspect"),
        ("L 90.8 Другие атрофические изменения кожи :", "scars"),
        ("Другие процедуры, не имеющие лечебных целей", "cosmetic"),
        ("обс", "checkup"),
        ("B35.1", "nails_feet"),  # ICD fallback, most specific prefix
        ("Vitiligo", "vitiligo"),  # Latin spelling
    ],
)
def test_rule_suggestions(text: str, code: str) -> None:
    assert suggest_category(text) == code


@pytest.mark.parametrize("text", ["", "   ", "Ўри. фарингит", "что-то непонятное"])
def test_no_suggestion_for_unknown_or_non_skin(text: str) -> None:
    assert suggest_category(text) is None


def test_category_codes_are_unique() -> None:
    assert len(CATEGORY_BY_CODE) == len(CATEGORIES)


# --- API --------------------------------------------------------------------------------------


async def _patient_with(*diagnoses: str, name: str = "Test Bemor") -> str:
    async with SessionLocal() as s:
        p = Patient(
            full_name=name,
            search_key=search_key(name),
            kind=PatientKind.LEGACY,
            tags=[],
            conditions=[PatientCondition(raw_text=d, source="test") for d in diagnoses],
        )
        s.add(p)
        await s.commit()
        return str(p.id)


@pytest.fixture
async def doctor(client: AsyncClient) -> dict[str, str]:
    await make_user("doc", Role.DOCTOR)
    return bearer(await login(client, "doc"))


async def test_sync_suggests_and_approval_categorizes_patients(
    client: AsyncClient, doctor: dict
) -> None:
    p1 = await _patient_with("Витилиго", name="Birinchi Bemor")
    await _patient_with("витилиго ", "Непонятный диагноз", name="Ikkinchi Bemor")

    synced = (await client.post("/api/diagnoses/sync", headers=doctor)).json()
    assert synced["mappings_suggested"] == 1 and synced["mappings_pending"] == 1

    page = (await client.get("/api/diagnoses/mappings", headers=doctor)).json()
    top = page["items"][0]
    assert (top["text"], top["category_code"], top["status"], top["patients"]) == (
        "витилиго",
        "vitiligo",
        "suggested",
        2,  # "Витилиго" and "витилиго " share one mapping
    )
    assert page["by_status"] == {"suggested": 1, "pending": 1}

    # a suggestion is not applied until approved
    none_yet = await client.get("/api/patients", params={"category": "vitiligo"}, headers=doctor)
    assert none_yet.status_code == 403  # doctors don't browse patients; check via stats instead
    cats = {
        c["code"]: c for c in (await client.get("/api/diagnoses/categories", headers=doctor)).json()
    }
    assert cats["vitiligo"]["patients"] == 0 and cats["vitiligo"]["suggested_texts"] == 1

    approved = await client.post(
        "/api/diagnoses/mappings/approve", json={"ids": [top["id"]]}, headers=doctor
    )
    assert approved.json() == {"approved": 1}

    cats = {
        c["code"]: c for c in (await client.get("/api/diagnoses/categories", headers=doctor)).json()
    }
    assert cats["vitiligo"]["patients"] == 2

    await make_user("op1", Role.OPERATOR)
    op = bearer(await login(client, "op1"))
    listed = await client.get("/api/patients", params={"category": "vitiligo"}, headers=op)
    assert p1 in [i["id"] for i in listed.json()["items"]] and listed.json()["total"] == 2


async def test_manual_category_for_pending_text(client: AsyncClient, doctor: dict) -> None:
    await _patient_with("Непонятный диагноз")
    await client.post("/api/diagnoses/sync", headers=doctor)
    [pending] = (
        await client.get("/api/diagnoses/mappings", params={"status": "pending"}, headers=doctor)
    ).json()["items"]

    bad = await client.put(
        f"/api/diagnoses/mappings/{pending['id']}", json={"category_code": "nope"}, headers=doctor
    )
    assert bad.status_code == 422

    ok = await client.put(
        f"/api/diagnoses/mappings/{pending['id']}", json={"category_code": "other"}, headers=doctor
    )
    assert ok.json()["status"] == "approved" and ok.json()["method"] == "manual"


async def test_only_doctors_and_admins_approve(client: AsyncClient) -> None:
    await _patient_with("Акне")
    await make_user("sup", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup"))

    assert (await client.post("/api/diagnoses/sync", headers=sup)).status_code == 403
    assert (await client.get("/api/diagnoses/mappings", headers=sup)).status_code == 200
    resp = await client.post(
        "/api/diagnoses/mappings/approve",
        json={"ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=sup,
    )
    assert resp.status_code == 403


async def test_sync_is_idempotent(client: AsyncClient, doctor: dict) -> None:
    await _patient_with("Акне")
    await client.post("/api/diagnoses/sync", headers=doctor)
    again = (await client.post("/api/diagnoses/sync", headers=doctor)).json()
    assert again.get("mappings_suggested", 0) == 0 and again.get("conditions_keyed", 0) == 0


async def test_registrars_read_categories_but_do_not_approve(client: AsyncClient) -> None:
    await make_user("reg", Role.REGISTRAR)
    reg = bearer(await login(client, "reg"))
    assert (await client.get("/api/diagnoses/categories", headers=reg)).status_code == 200
    assert (await client.get("/api/diagnoses/mappings", headers=reg)).status_code == 200
    assert (await client.post("/api/diagnoses/sync", headers=reg)).status_code == 403
