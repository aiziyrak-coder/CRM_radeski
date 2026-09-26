from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.audit.models import AuditLog
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user


def patient_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "full_name": "Каримова Дилноза",
        "birth_date": "1985-04-12",
        "gender": "female",
        "district": "Oltiariq",
        "source": "instagram",
        "phones": [{"number": "90-000-12-34"}],
    }
    return {**body, **overrides}


@pytest.fixture
async def op(client: AsyncClient) -> dict[str, str]:
    await make_user("op1", Role.OPERATOR)
    return bearer(await login(client, "op1"))


async def create(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict:
    resp = await client.post("/api/patients", json=patient_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_normalizes_phone_and_sets_primary(client: AsyncClient, op: dict) -> None:
    p = await create(client, op)

    assert p["phones"] == [
        {
            "id": p["phones"][0]["id"],
            "number": "+998900001234",
            "display": "+998 90 000-12-34",
            "is_primary": True,
            "note": None,
        }
    ]
    assert p["kind"] == "active"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phones", [{"number": "123"}]),
        ("phones", []),
        ("birth_date", "6989-01-01"),  # seen in the legacy export
        ("full_name", " "),
        ("source", "tv"),
    ],
)
async def test_invalid_input_rejected(
    client: AsyncClient, op: dict, field: str, value: Any
) -> None:
    resp = await client.post("/api/patients", json=patient_body(**{field: value}), headers=op)
    assert resp.status_code == 422


async def test_same_phone_is_flagged_as_possible_duplicate(client: AsyncClient, op: dict) -> None:
    first = await create(client, op)

    # a child registered with the mother's phone: different person, same number
    body = patient_body(full_name="Каримов Али", birth_date="2015-03-01")
    resp = await client.post("/api/patients", json=body, headers=op)

    assert resp.status_code == 409
    [candidate] = resp.json()["candidates"]
    assert candidate["id"] == first["id"] and candidate["reasons"] == ["phone"]

    forced = await client.post("/api/patients?force=true", json=body, headers=op)
    assert forced.status_code == 201


async def test_same_person_in_other_script_is_flagged(client: AsyncClient, op: dict) -> None:
    first = await create(client, op)

    resp = await client.post(
        "/api/patients",
        json=patient_body(full_name="Karimova Dilnoza", phones=[{"number": "901112233"}]),
        headers=op,
    )

    assert resp.status_code == 409
    assert resp.json()["candidates"][0]["id"] == first["id"]
    assert resp.json()["candidates"][0]["reasons"] == ["name"]


async def test_namesake_with_other_birth_date_is_not_a_duplicate(
    client: AsyncClient, op: dict
) -> None:
    await create(client, op)
    body = patient_body(birth_date="1990-01-01", phones=[{"number": "901112233"}])
    assert (await client.post("/api/patients", json=body, headers=op)).status_code == 201


@pytest.mark.parametrize(
    "q", ["Каримова", "karimova", "Qarimova Dilnoza", "dilnoza karimova", "1234", "90 000"]
)
async def test_search_across_scripts_and_by_phone(client: AsyncClient, op: dict, q: str) -> None:
    target = await create(client, op)
    await create(
        client,
        op,
        full_name="Тошматов Бобур",
        birth_date="2001-02-03",
        phones=[{"number": "907770011"}],
    )

    resp = await client.get("/api/patients", params={"q": q}, headers=op)

    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()["items"]]
    assert ids and ids[0] == target["id"]


async def test_search_tolerates_typos(client: AsyncClient, op: dict) -> None:
    target = await create(client, op)
    resp = await client.get("/api/patients", params={"q": "Karimova Dilnaza"}, headers=op)
    assert target["id"] in [i["id"] for i in resp.json()["items"]]


async def test_viewing_a_card_is_audited(client: AsyncClient, op: dict) -> None:
    p = await create(client, op)

    assert (await client.get(f"/api/patients/{p['id']}", headers=op)).status_code == 200

    async with SessionLocal() as s:
        views = await s.scalar(
            select(func.count()).where(
                AuditLog.action == "patient.view", AuditLog.entity_id == p["id"]
            )
        )
    assert views == 1


async def test_update_keeps_search_in_sync(client: AsyncClient, op: dict) -> None:
    p = await create(client, op)

    resp = await client.patch(
        f"/api/patients/{p['id']}", json={"full_name": "Юлдашева Нигора"}, headers=op
    )

    assert resp.status_code == 200
    found = await client.get("/api/patients", params={"q": "yuldasheva"}, headers=op)
    assert [i["id"] for i in found.json()["items"]] == [p["id"]]


async def test_phone_management(client: AsyncClient, op: dict) -> None:
    p = await create(client, op)
    pid, first_phone = p["id"], p["phones"][0]["id"]

    resp = await client.post(
        f"/api/patients/{pid}/phones",
        json={"number": "+998 91 234 56 78", "note": "onasi", "is_primary": True},
        headers=op,
    )
    phones = resp.json()["phones"]
    assert [ph["number"] for ph in phones] == ["+998912345678", "+998900001234"]
    assert [ph["is_primary"] for ph in phones] == [True, False]

    resp = await client.delete(f"/api/patients/{pid}/phones/{phones[0]['id']}", headers=op)
    assert resp.json()["phones"][0]["is_primary"] is True

    last = await client.delete(f"/api/patients/{pid}/phones/{first_phone}", headers=op)
    assert last.status_code == 400 and last.json()["detail"] == "last_phone"


async def test_do_not_call_flag(client: AsyncClient, op: dict) -> None:
    p = await create(client, op)

    resp = await client.put(
        f"/api/patients/{p['id']}/do-not-call",
        json={"do_not_call": True, "reason": "boshqa qo'ng'iroq qilmang dedi"},
        headers=op,
    )

    assert resp.json()["do_not_call"] is True
    assert resp.json()["do_not_call_reason"] == "boshqa qo'ng'iroq qilmang dedi"


async def test_merge_moves_phones_and_hides_source(client: AsyncClient) -> None:
    await make_user("sup", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup"))
    target = await create(client, sup, address=None)
    source = (
        await client.post(
            "/api/patients?force=true",
            json=patient_body(
                full_name="Karimova Dilnoza",
                address="Oltiariq, Namuna ko'chasi 1",
                phones=[{"number": "901112233"}, {"number": "900001234"}],
                tags=["alopesiya"],
            ),
            headers=sup,
        )
    ).json()

    resp = await client.post(
        f"/api/patients/{target['id']}/merge", json={"source_id": source["id"]}, headers=sup
    )

    assert resp.status_code == 200
    merged = resp.json()
    assert sorted(ph["number"] for ph in merged["phones"]) == ["+998900001234", "+998901112233"]
    assert merged["address"] == "Oltiariq, Namuna ko'chasi 1"
    assert merged["tags"] == ["alopesiya"]

    listed = await client.get("/api/patients", params={"q": "karimova"}, headers=sup)
    assert [i["id"] for i in listed.json()["items"]] == [target["id"]]

    gone = await client.get(f"/api/patients/{source['id']}", headers=sup)
    assert gone.json()["merged_into_id"] == target["id"]
    edit = await client.patch(f"/api/patients/{source['id']}", json={"notes": "x"}, headers=sup)
    assert edit.status_code == 409

    again = await client.post(
        f"/api/patients/{target['id']}/merge", json={"source_id": source["id"]}, headers=sup
    )
    assert again.status_code == 400


async def test_operator_cannot_merge(client: AsyncClient, op: dict) -> None:
    a = await create(client, op)
    b = await create(client, op, full_name="Boshqa Odam", phones=[{"number": "901112233"}])
    resp = await client.post(
        f"/api/patients/{a['id']}/merge", json={"source_id": b["id"]}, headers=op
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.OWNER])
async def test_roles_without_patient_access(client: AsyncClient, role: Role) -> None:
    await make_user("someone", role)
    headers = bearer(await login(client, "someone"))
    assert (await client.get("/api/patients", headers=headers)).status_code == 403


async def test_registrar_can_register_walk_in(client: AsyncClient) -> None:
    await make_user("reg", Role.REGISTRAR)
    headers = bearer(await login(client, "reg"))
    assert (await create(client, headers))["full_name"] == "Каримова Дилноза"


async def test_default_list_hides_cold_base_but_search_finds_it(
    client: AsyncClient, op: dict
) -> None:
    named = await create(client, op)
    async with SessionLocal() as s:
        from app.core.text import search_key
        from app.modules.patients.models import Patient, PatientKind, PatientPhone

        s.add(
            Patient(
                full_name="Ismi noma'lum",
                search_key=search_key("Ismi noma'lum"),
                kind=PatientKind.COLD,
                tags=[],
                phones=[PatientPhone(number="+998935550000", is_primary=True)],
            )
        )
        await s.commit()

    listed = await client.get("/api/patients", headers=op)
    assert [i["id"] for i in listed.json()["items"]] == [named["id"]]

    cold = await client.get("/api/patients", params={"kind": "cold"}, headers=op)
    assert cold.json()["total"] == 1
    by_phone = await client.get("/api/patients", params={"q": "5550000"}, headers=op)
    assert by_phone.json()["total"] == 1
