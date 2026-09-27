"""Inbox conversation search: title, phone (or a part), patient name in either script, text."""

from datetime import UTC, datetime

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.text import search_key
from app.modules.messaging.models import Channel, Conversation, Direction, Message, MessageStatus
from app.modules.patients.models import Patient, PatientKind


async def _seed() -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        patient = Patient(
            full_name="Абдуллаев Жасур", search_key=search_key("Абдуллаев Жасур"),
            kind=PatientKind.ACTIVE, tags=[],
        )  # fmt: skip
        s.add(patient)
        await s.flush()
        tg = Conversation(
            channel=Channel.TELEGRAM, external_id="555", title="@jasur_a", patient_id=patient.id,
            last_message_at=now, unread=0,
        )  # fmt: skip
        ig = Conversation(
            channel=Channel.INSTAGRAM, external_id="ig-1", title="malika.beauty",
            phone="+998911112233", last_message_at=now, unread=1,
        )  # fmt: skip
        sms = Conversation(
            channel=Channel.SMS, external_id="+998935556677", last_message_at=now, unread=0
        )
        s.add_all([tg, ig, sms])
        await s.flush()
        s.add_all(
            [
                Message(conversation_id=ig.id, direction=Direction.IN, created_at=now,
                        text="Lazer epilyatsiya narxi 100% qancha?", status=MessageStatus.RECEIVED),
                Message(conversation_id=sms.id, direction=Direction.OUT, created_at=now,
                        text="Ertaga soat 10:00 da kutamiz", status=MessageStatus.SENT),
            ]
        )  # fmt: skip
        await s.commit()


async def test_conversation_search(client: AsyncClient, op: dict) -> None:
    await _seed()

    async def titles(q: str, **extra: str) -> list[str | None]:
        resp = await client.get(
            "/api/messaging/conversations", params={"q": q, **extra}, headers=op
        )
        assert resp.status_code == 200, resp.text
        return sorted(c["title"] or c["channel"] for c in resp.json())

    assert await titles("malika") == ["malika.beauty"]
    assert await titles("Abdullayev") == ["@jasur_a"]  # Cyrillic name found by Latin query
    assert await titles("абдуллаев") == ["@jasur_a"]
    assert await titles("11 22") == ["malika.beauty"]  # part of the phone, any spacing
    assert await titles("5556") == ["sms"]  # SMS chats are keyed by the number
    assert await titles("lazer") == ["malika.beauty"]  # message text
    assert await titles("100%") == ["malika.beauty"]  # % is literal, not a wildcard
    assert await titles("ertaga", channel="telegram") == []
    assert await titles("yo'q narsa") == []
    everything = await client.get("/api/messaging/conversations", headers=op)
    assert len(everything.json()) == 3
