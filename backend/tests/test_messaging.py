"""Phase 5: Telegram/Instagram inbox, SMS templates and reminders, AI drafts.

The providers are replaced by httpx MockTransports: request shapes are checked, nothing leaves.
"""

import asyncio
import hashlib
import hmac
import itertools
import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.integrations.instagram import InstagramClient
from app.integrations.sms import eskiz
from app.integrations.sms.eskiz import EskizSms
from app.integrations.sms.playmobile import PlaymobileSms
from app.integrations.telegram import TelegramBot
from app.modules.leads.models import Lead
from app.modules.messaging import rules as messaging_rules
from app.modules.messaging import service
from app.modules.messaging.models import Channel, Conversation, Message
from app.modules.tasks.models import Task, TaskType
from app.modules.users.models import Role
from tests.conftest import bearer, login, make_user
from tests.factories import at, booking, next_monday

TG_SECRET = "tg-secret"


class Recorder:
    """A fake provider: remembers requests, answers with a canned response."""

    def __init__(self, answer: Any = None, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.answer = answer
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answer(request) if callable(self.answer) else self.answer
        return httpx.Response(self.status, json=answer)

    def json(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


@pytest.fixture
def channels(monkeypatch: pytest.MonkeyPatch) -> dict[str, Recorder]:
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(s, "telegram_webhook_secret", TG_SECRET)
    monkeypatch.setattr(s, "instagram_access_token", "ig-token")
    monkeypatch.setattr(s, "instagram_app_secret", "ig-secret")
    monkeypatch.setattr(s, "instagram_verify_token", "verify-me")
    monkeypatch.setattr(s, "instagram_user_id", "1784")
    monkeypatch.setattr(s, "sms_provider", "eskiz")
    monkeypatch.setattr(s, "eskiz_callback_secret", "cb-secret")
    monkeypatch.setattr(s, "messages_from_hour", 0)  # no quiet hours unless a test sets them
    monkeypatch.setattr(s, "messages_to_hour", 24)
    rec = {
        "telegram": Recorder({"ok": True, "result": {"message_id": 77}}),
        "instagram": Recorder({"message_id": "mid.1"}),
        "eskiz": Recorder(
            lambda r: (
                {"data": {"token": "tok"}}
                if r.url.path.endswith("/login")
                else {"id": "esk-1", "status": "waiting"}
            )
        ),
    }
    monkeypatch.setattr(eskiz, "_token", None)
    monkeypatch.setattr(
        service, "get_telegram", lambda: TelegramBot(transport=httpx.MockTransport(rec["telegram"]))
    )
    monkeypatch.setattr(
        service,
        "get_instagram",
        lambda: InstagramClient(transport=httpx.MockTransport(rec["instagram"])),
    )
    monkeypatch.setattr(
        service, "get_sms_sender", lambda: EskizSms(transport=httpx.MockTransport(rec["eskiz"]))
    )
    return rec


_msg_ids = itertools.count(1)


def tg_update(text: str | None = None, *, chat_id: int = 555, **extra: Any) -> dict:
    message = {
        "message_id": next(_msg_ids),
        "from": {"id": chat_id, "first_name": "Aziza", "language_code": "uz"},
        "chat": {"id": chat_id, "type": "private", "first_name": "Aziza", "last_name": "Sinov"},
        "date": 1,
        **({"text": text} if text is not None else {}),
        **extra,
    }
    return {"update_id": 1, "message": message}


async def post_tg(client: AsyncClient, update: dict, secret: str = TG_SECRET):
    return await client.post(
        "/api/integrations/telegram/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )


async def conv_messages(channel: Channel, external_id: str) -> tuple[Conversation, list[Message]]:
    async with SessionLocal() as s:
        conv = await s.scalar(
            select(Conversation).where(
                Conversation.channel == channel, Conversation.external_id == external_id
            )
        )
        msgs = list(
            await s.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at)
            )
        )
        return conv, msgs


async def deliver_all() -> None:
    async with SessionLocal() as s:
        for mid in await service.due_messages(s):
            await service.deliver(s, mid)
        await s.commit()


# --- Telegram ---------------------------------------------------------------------------------


async def test_telegram_start_message_and_contact(
    client: AsyncClient, clinic: dict, op: dict, channels: dict
) -> None:
    assert (await post_tg(client, tg_update("salom"), secret="wrong")).status_code == 401

    start = (await post_tg(client, tg_update("/start"))).json()
    assert start["method"] == "sendMessage" and start["chat_id"] == 555
    assert start["reply_markup"]["keyboard"][0][0]["request_contact"] is True

    await post_tg(client, tg_update("Soch to'kilishi bo'yicha maslahat kerak"))
    conv, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert conv.title == "Aziza Sinov" and conv.unread == 1
    assert [m.direction for m in msgs] == ["out", "in"]  # the welcome is in the history too
    async with SessionLocal() as s:
        lead = await s.get(Lead, conv.lead_id)
        [task] = list(await s.scalars(select(Task).where(Task.type == TaskType.NEW_LEAD)))
    assert lead.channel == "telegram" and "Soch" in lead.interest and task.lead_id == lead.id

    # sharing the contact links the chat to the existing patient card
    reply = await post_tg(
        client,
        tg_update(contact={"phone_number": "998900000001", "user_id": 555, "first_name": "A"}),
    )
    assert reply.json()["reply_markup"] == {"remove_keyboard": True}
    conv, _ = await conv_messages(Channel.TELEGRAM, "555")
    assert conv.phone == "+998900000001" and str(conv.patient_id) == clinic["patient"]
    async with SessionLocal() as s:
        assert len(list(await s.scalars(select(Lead)))) == 1  # same open inquiry
    feed = (await client.get(f"/api/patients/{clinic['patient']}/timeline", headers=op)).json()
    chat = [e for e in feed if e["kind"] == "message"]
    assert {e["title"] for e in chat} == {"telegram"} and len(chat) == 4


async def test_business_account_replies_are_logged(client: AsyncClient, channels: dict) -> None:
    msg = tg_update("Narxi qancha?")["message"]
    await client.post(
        "/api/integrations/telegram/webhook",
        json={"update_id": 2, "business_message": {**msg, "business_connection_id": "bc-1"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
    )
    owner_reply = {**msg, "from": {"id": 999, "first_name": "Clinic"}, "text": "200 000 so'm"}
    await client.post(
        "/api/integrations/telegram/webhook",
        json={
            "update_id": 3,
            "business_message": {**owner_reply, "business_connection_id": "bc-1"},
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
    )
    conv, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert conv.business_connection_id == "bc-1"
    assert [(m.direction, m.status) for m in msgs] == [("in", "received"), ("out", "sent")]


async def test_operator_reply_is_sent_and_answers_the_inquiry(
    client: AsyncClient, op: dict, channels: dict
) -> None:
    await post_tg(client, tg_update("Salom, qabulga yozilmoqchiman"))
    conv, _ = await conv_messages(Channel.TELEGRAM, "555")
    listed = (await client.get("/api/messaging/conversations", headers=op)).json()
    assert listed[0]["unread"] == 1 and listed[0]["last_text"].startswith("Salom")
    assert (await client.get("/api/messaging/unread", headers=op)).json() == {"conversations": 1}

    resp = await client.post(
        f"/api/messaging/conversations/{conv.id}/messages",
        json={"text": "Assalomu alaykum! Qaysi kun qulay?"},
        headers=op,
    )
    assert resp.status_code == 201 and resp.json()["status"] == "queued"
    await deliver_all()
    sent = channels["telegram"].json()
    assert sent == {"chat_id": "555", "text": "Assalomu alaykum! Qaysi kun qulay?"}
    assert channels["telegram"].requests[-1].url.path == "/bot123:abc/sendMessage"
    conv, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert msgs[-1].status == "sent" and msgs[-1].external_id == "77" and conv.unread == 0
    async with SessionLocal() as s:
        assert (await s.get(Lead, conv.lead_id)).first_response_at is not None

    thread = (await client.get(f"/api/messaging/conversations/{conv.id}", headers=op)).json()
    assert [m["direction"] for m in thread["messages"]] == ["in", "out"]
    assert thread["messages"][1]["sent_by_name"]


async def test_failed_sends_retry_then_give_up(
    client: AsyncClient, op: dict, channels: dict
) -> None:
    await post_tg(client, tg_update("salom"))
    conv, _ = await conv_messages(Channel.TELEGRAM, "555")
    channels["telegram"].answer = {"ok": False, "description": "Forbidden: bot was blocked"}
    await client.post(
        f"/api/messaging/conversations/{conv.id}/messages", json={"text": "javob"}, headers=op
    )
    for _ in range(3):
        await deliver_all()
    _, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert msgs[-1].status == "failed" and msgs[-1].attempts == 3
    assert "blocked" in msgs[-1].error and "123:abc" not in msgs[-1].error


# --- Instagram --------------------------------------------------------------------------------


async def test_instagram_webhook(client: AsyncClient, channels: dict) -> None:
    ok = await client.get(
        "/api/integrations/instagram/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = await client.get(
        "/api/integrations/instagram/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403

    payload = {
        "object": "instagram",
        "entry": [{"id": "1784", "messaging": [
            {"sender": {"id": "ig-9"}, "recipient": {"id": "1784"},
             "message": {"mid": "m1", "text": "Lazer epilyatsiya narxi?"}},
            {"sender": {"id": "1784"}, "recipient": {"id": "ig-9"},
             "message": {"mid": "m2", "text": "Salom!", "is_echo": True}},
        ]}],
    }  # fmt: skip
    body = json.dumps(payload).encode()
    sig = hmac.new(b"ig-secret", body, hashlib.sha256).hexdigest()
    unsigned = await client.post("/api/integrations/instagram/webhook", content=body)
    assert unsigned.status_code == 401
    resp = await client.post(
        "/api/integrations/instagram/webhook",
        content=body,
        headers={"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"},
    )
    assert resp.json() == {"handled": 2}
    conv, msgs = await conv_messages(Channel.INSTAGRAM, "ig-9")
    assert [m.direction for m in msgs] == ["in", "out"]
    async with SessionLocal() as s:
        assert (await s.get(Lead, conv.lead_id)).channel == "instagram"

    await service_queue_and_deliver(conv, "Narxi 300 000 so'm")
    assert channels["instagram"].json() == {
        "recipient": {"id": "ig-9"},
        "message": {"text": "Narxi 300 000 so'm"},
    }
    assert channels["instagram"].requests[-1].url.path == "/v23.0/1784/messages"


async def service_queue_and_deliver(conv: Conversation, text: str) -> None:
    async with SessionLocal() as s:
        c = await s.get(Conversation, conv.id)
        await service.queue(s, c, text, user_id=None)
        await s.commit()
    await deliver_all()


# --- SMS, reminders ---------------------------------------------------------------------------


async def test_booking_confirmation_reminder_and_delivery_report(
    client: AsyncClient, clinic: dict, op: dict, channels: dict
) -> None:
    body = booking(clinic, at(next_monday(), 9))
    assert (await client.post("/api/appointments", json=body, headers=op)).status_code == 201
    conv, msgs = await conv_messages(Channel.SMS, "+998900000001")
    assert [m.template_code for m in msgs] == ["appointment_confirmed"]
    assert "09:00" in msgs[0].text and "Doktor A" in msgs[0].text

    await deliver_all()
    login_req, send_req = channels["eskiz"].requests
    assert login_req.url.path == "/api/auth/login"
    form = dict(httpx.QueryParams(send_req.content.decode()))
    assert form["mobile_phone"] == "998900000001" and form["from"] == "4546"
    assert send_req.headers["Authorization"] == "Bearer tok"
    assert form["callback_url"].endswith("/api/integrations/sms/eskiz/cb-secret")

    report = await client.post(
        "/api/integrations/sms/eskiz/cb-secret", json={"message_id": "esk-1", "status": "DELIVRD"}
    )
    assert report.json() == {"ok": True}
    _, msgs = await conv_messages(Channel.SMS, "+998900000001")
    assert msgs[0].status == "delivered"

    async with SessionLocal() as s:
        assert await messaging_rules.send_reminders(s, next_monday()) == 1
        assert await messaging_rules.send_reminders(s, next_monday()) == 0  # once only
        await s.commit()
    _, msgs = await conv_messages(Channel.SMS, "+998900000001")
    assert msgs[-1].template_code == "appointment_reminder" and "ertaga" in msgs[-1].text


async def test_unreachable_message_after_second_attempt(
    client: AsyncClient, clinic: dict, op: dict, channels: dict
) -> None:
    await client.post(
        "/api/tasks",
        json={"patient_id": clinic["patient"], "due_at": clinic_time.now().isoformat()},
        headers=op,
    )
    async with SessionLocal() as s:
        [task] = list(await s.scalars(select(Task).where(Task.type == TaskType.CALLBACK)))
    url = f"/api/tasks/{task.id}/result"
    await client.post(url, json={"outcome": "no_answer"}, headers=op)
    async with SessionLocal() as s:
        assert not list(await s.scalars(select(Message)))
    await client.post(url, json={"outcome": "no_answer"}, headers=op)
    _, msgs = await conv_messages(Channel.SMS, "+998900000001")
    assert [m.template_code for m in msgs] == ["unreachable"]


def test_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "messages_from_hour", 9)
    monkeypatch.setattr(s, "messages_to_hour", 20)
    tz = clinic_time.tz()
    night = datetime(2026, 9, 28, 22, 30, tzinfo=tz)
    morning = datetime(2026, 9, 29, 7, 0, tzinfo=tz)
    noon = datetime(2026, 9, 29, 12, 0, tzinfo=tz)
    assert service._next_allowed(night) == datetime(2026, 9, 29, 9, 0, tzinfo=tz)
    assert service._next_allowed(morning) == datetime(2026, 9, 29, 9, 0, tzinfo=tz)
    assert service._next_allowed(noon) == noon


async def test_playmobile_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "playmobile_login", "user")
    monkeypatch.setattr(s, "playmobile_password", "pass")
    rec = Recorder("Request is received")
    sms = PlaymobileSms(transport=httpx.MockTransport(rec))
    assert await sms.send("+998900002244", "Salom", "0f8f-12") == "0f8f12"
    body = rec.json()
    assert body["messages"][0]["recipient"] == "998900002244"
    assert body["messages"][0]["sms"]["content"]["text"] == "Salom"
    assert rec.requests[0].headers["Authorization"].startswith("Basic ")


# --- templates, SMS thread, AI draft ----------------------------------------------------------


async def test_templates_sms_thread_and_draft(
    client: AsyncClient, clinic: dict, op: dict, channels: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    templates = (await client.get("/api/messaging/templates", headers=op)).json()
    assert {t["code"] for t in templates} >= {"appointment_confirmed", "unreachable"}
    tpl = templates[0]
    assert (
        await client.put(
            f"/api/messaging/templates/{tpl['id']}",
            json={"title": tpl["title"], "text": tpl["text"], "active": True},
            headers=op,
        )
    ).status_code == 403
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    changed = await client.put(
        f"/api/messaging/templates/{tpl['id']}",
        json={"title": tpl["title"], "text": "Yangi matn {telefon}", "active": True},
        headers=sup,
    )
    assert changed.status_code == 200 and changed.json()["text"] == "Yangi matn {telefon}"

    thread = (
        await client.post(f"/api/messaging/patients/{clinic['patient']}/sms", headers=op)
    ).json()
    assert thread["channel"] == "sms" and thread["phone"] is None and thread["patient_name"]
    rendered = await client.post(
        f"/api/messaging/conversations/{thread['id']}/render",
        json={"code": "unreachable"},
        headers=op,
    )
    assert rendered.status_code == 200 and "Radeski" in rendered.json()["text"]

    assert (
        await client.post(f"/api/messaging/conversations/{thread['id']}/draft", headers=op)
    ).status_code == 503  # AI off

    from app.modules.messaging import drafts

    class FakeLlm:
        name = "fake"

        async def parse(self, *, system, user, schema, cache_key):
            assert "Radeski" in system and "Chat so far" in user
            return schema(text="Assalomu alaykum! Qaysi kun qulay?")

    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    monkeypatch.setattr(drafts, "get_llm", lambda: FakeLlm())
    draft = await client.post(f"/api/messaging/conversations/{thread['id']}/draft", headers=op)
    assert draft.json() == {"text": "Assalomu alaykum! Qaysi kun qulay?"}


# --- delivery safety, webhook idempotency -----------------------------------------------------


async def _operator_message(client: AsyncClient, op: dict, text: str = "javob") -> Message:
    await post_tg(client, tg_update("salom"))
    conv, _ = await conv_messages(Channel.TELEGRAM, "555")
    resp = await client.post(
        f"/api/messaging/conversations/{conv.id}/messages", json={"text": text}, headers=op
    )
    async with SessionLocal() as s:
        return await s.get(Message, resp.json()["id"])


def _sends(rec: Recorder) -> int:
    return sum(r.url.path.endswith("/sendMessage") for r in rec.requests)


async def test_a_message_is_sent_once_by_concurrent_workers(
    client: AsyncClient, op: dict, channels: dict
) -> None:
    """The immediate task and the per-minute job pick up the same queued message."""
    msg = await _operator_message(client, op)

    async def worker() -> Any:
        async with SessionLocal() as s:
            return await service.deliver(s, msg.id)

    results = await asyncio.gather(worker(), worker(), worker())
    assert sorted(results, key=str) == [None, None, "sent"]
    await deliver_all()
    assert _sends(channels["telegram"]) == 1
    async with SessionLocal() as s:
        stored = await s.get(Message, msg.id)
    assert stored.status == "sent" and stored.claimed_at is not None


async def test_interrupted_send_is_failed_not_resent(
    client: AsyncClient, op: dict, channels: dict
) -> None:
    msg = await _operator_message(client, op)
    async with SessionLocal() as s:
        stored = await s.get(Message, msg.id)
        stored.status = "sending"  # a worker took it and died
        stored.claimed_at = clinic_time.now() - timedelta(minutes=11)
        await s.commit()
    async with SessionLocal() as s:
        assert await service.deliver_due(s) == 0
    async with SessionLocal() as s:
        stored = await s.get(Message, msg.id)
    assert stored.status == "failed" and stored.error == "interrupted"
    assert _sends(channels["telegram"]) == 0


async def test_one_broken_message_does_not_undo_the_others(
    client: AsyncClient, op: dict, channels: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _operator_message(client, op, "birinchi")
    second = await _operator_message(client, op, "ikkinchi")
    real = service.deliver

    async def flaky(session, message_id):
        if message_id == second.id:
            raise RuntimeError("database hiccup")
        return await real(session, message_id)

    monkeypatch.setattr(service, "deliver", flaky)
    async with SessionLocal() as s:
        assert await service.deliver_due(s) == 2
    async with SessionLocal() as s:
        assert (await s.get(Message, first.id)).status == "sent"  # committed, not rolled back
        assert (await s.get(Message, second.id)).status == "queued"  # next minute
    monkeypatch.setattr(service, "deliver", real)

    # a provider answer we can't read: maybe sent, so never resent automatically
    async def garbled(conv, msg):
        raise KeyError("message_id")

    monkeypatch.setattr(service, "_send", garbled)
    await deliver_all()
    async with SessionLocal() as s:
        stored = await s.get(Message, second.id)
    assert stored.status == "failed" and stored.error == "unexpected: KeyError"


async def test_automatic_messages_wait_for_the_day_at_delivery(
    client: AsyncClient, channels: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await post_tg(client, tg_update("salom"))
    conv, _ = await conv_messages(Channel.TELEGRAM, "555")
    async with SessionLocal() as s:
        msg = await service.queue(s, await s.get(Conversation, conv.id), "Eslatma", user_id=None)
        await s.commit()
    # it fell due during the day, but the worker only gets to it at night (an outage)
    hour = clinic_time.local(clinic_time.now()).hour
    settings = get_settings()
    monkeypatch.setattr(settings, "messages_from_hour", hour + 1 if hour < 23 else 0)
    monkeypatch.setattr(settings, "messages_to_hour", 24 if hour < 23 else 23)
    await deliver_all()
    assert _sends(channels["telegram"]) == 0
    async with SessionLocal() as s:
        stored = await s.get(Message, msg.id)
    assert stored.status == "queued" and stored.send_after > clinic_time.now()


async def test_instagram_echo_of_our_own_message_is_not_a_second_message(
    client: AsyncClient, channels: dict
) -> None:
    async def webhook(*events: dict) -> None:
        body = json.dumps({"object": "instagram", "entry": [{"messaging": list(events)}]}).encode()
        sig = hmac.new(b"ig-secret", body, hashlib.sha256).hexdigest()
        await client.post(
            "/api/integrations/instagram/webhook",
            content=body,
            headers={"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"},
        )

    def echo(mid: str, text: str) -> dict:
        return {"sender": {"id": "1784"}, "recipient": {"id": "ig-9"},
                "message": {"mid": mid, "text": text, "is_echo": True}}  # fmt: skip

    inbound = {"sender": {"id": "ig-9"}, "recipient": {"id": "1784"},
               "message": {"mid": "m1", "text": "Narxi?"}}  # fmt: skip
    await webhook(inbound)
    await webhook(inbound)  # Meta retries: stored once, counted once
    conv, msgs = await conv_messages(Channel.INSTAGRAM, "ig-9")
    assert [m.direction for m in msgs] == ["in"] and conv.unread == 1

    await service_queue_and_deliver(conv, "300 000 so'm")  # the API answers mid.1
    await webhook(echo("mid.1", "300 000 so'm"))
    # the echo may even come before we stored the id: our row stays, the echo row goes
    channels["instagram"].answer = {"message_id": "mid.2"}
    async with SessionLocal() as s:
        queued = await service.queue(s, await s.get(Conversation, conv.id), "Manzil", user_id=None)
        await s.commit()
    await webhook(echo("mid.2", "Manzil"))
    await deliver_all()
    # the clinic answering from the Instagram app itself is kept
    await webhook(echo("mid.3", "Telefondan javob"))
    _, msgs = await conv_messages(Channel.INSTAGRAM, "ig-9")
    assert [(m.direction, m.external_id) for m in msgs] == [
        ("in", "m1"), ("out", "mid.1"), ("out", "mid.2"), ("out", "mid.3"),
    ]  # fmt: skip
    assert next(m for m in msgs if m.external_id == "mid.2").id == queued.id


async def test_telegram_retries_and_business_bot_messages_are_not_duplicated(
    client: AsyncClient, channels: dict
) -> None:
    update = tg_update("Narxi qancha?")
    await post_tg(client, update)
    await post_tg(client, update)  # Telegram re-delivers when our answer was slow
    conv, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert len(msgs) == 1 and conv.unread == 1
    async with SessionLocal() as s:
        assert len(list(await s.scalars(select(Lead)))) == 1

    base = {**tg_update("x")["message"], "business_connection_id": "bc-1"}
    # sent by this bot on the clinic's behalf (an operator's reply from the CRM)
    ours = {**base, "message_id": 900, "from": {"id": 999}, "text": "CRM javobi",
            "sender_business_bot": {"id": 123, "is_bot": True}}  # fmt: skip
    # typed by the clinic in its own Telegram app
    manual = {**base, "message_id": 901, "from": {"id": 999}, "text": "Qo'lda javob"}
    for message in (ours, manual, manual):
        await post_tg(client, {"update_id": 5, "business_message": message})
    _, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert [(m.direction, m.text) for m in msgs] == [
        ("in", "Narxi qancha?"), ("out", "Qo'lda javob"),
    ]  # fmt: skip


async def test_concurrent_first_messages_open_one_chat_and_one_inquiry(channels: dict) -> None:
    async def arrive(text: str, mid: str) -> None:
        async with SessionLocal() as s:
            await service.receive(s, Channel.TELEGRAM, "777", text, external_msg_id=mid)
            await s.commit()

    await asyncio.gather(arrive("Salom", "1"), arrive("Narxlar?", "2"), arrive("Salom", "1"))
    async with SessionLocal() as s:
        convs = list(await s.scalars(select(Conversation)))
        leads = list(await s.scalars(select(Lead)))
        msgs = list(await s.scalars(select(Message)))
    assert len(convs) == 1 and len(leads) == 1 and len(msgs) == 2
    assert convs[0].unread == 2 and convs[0].lead_id == leads[0].id


async def test_someone_elses_contact_does_not_link_the_chat(
    client: AsyncClient, clinic: dict, channels: dict
) -> None:
    card = {"phone_number": "998900000001", "first_name": "Boshqa"}
    await post_tg(client, tg_update(contact={**card, "user_id": 4242}))  # a forwarded card
    await post_tg(client, tg_update(contact=card))  # typed in, no user_id
    conv, msgs = await conv_messages(Channel.TELEGRAM, "555")
    assert conv.phone is None and conv.patient_id is None
    assert [m.direction for m in msgs] == ["in", "in"]  # no "thank you" either


async def test_sms_thread_rejects_invalid_number(
    client: AsyncClient, clinic: dict, op: dict, channels: dict
) -> None:
    from app.modules.patients.models import PatientPhone

    async with SessionLocal() as s:
        for phone in await s.scalars(
            select(PatientPhone).where(PatientPhone.patient_id == clinic["patient"])
        ):
            phone.number = "+4915112345"
        await s.commit()
    resp = await client.post(f"/api/messaging/patients/{clinic['patient']}/sms", headers=op)
    assert resp.status_code == 409 and resp.json()["detail"] == "invalid_phone"
    async with SessionLocal() as s:
        assert not list(await s.scalars(select(Conversation)))


async def test_eskiz_reports_need_the_secret_and_touch_only_sms(
    client: AsyncClient, op: dict, channels: dict
) -> None:
    msg = await _operator_message(client, op)
    await deliver_all()  # Telegram message id "77"
    report = {"message_id": "77", "status": "UNDELIV"}
    assert (await client.post("/api/integrations/sms/eskiz/wrong", json=report)).status_code == 401
    ok = await client.post("/api/integrations/sms/eskiz/cb-secret", json=report)
    assert ok.json() == {"ok": False}
    async with SessionLocal() as s:
        assert (await s.get(Message, msg.id)).status == "sent"
