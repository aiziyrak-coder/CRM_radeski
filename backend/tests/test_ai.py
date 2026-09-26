"""Phase 4: call transcription + QA analysis, operator review, QA panel, brief, digest.

OpenAI is replaced by fakes: the pipeline, scoring, masking and API are what's tested here.
"""

import time as systime
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.integrations.llm import LlmError
from app.integrations.stt import Segment
from app.modules.ai import qa
from app.modules.ai import service as ai
from app.modules.ai.models import CallAnalysis
from app.modules.ai.prompts import AnalysisOut, Extracted, mask_pii
from app.modules.diagnoses.models import DiagnosisMapping, MappingStatus
from app.modules.scripts.router import seed_if_empty
from app.modules.tasks.models import Task, TaskStatus, TaskType
from app.modules.telephony import router as telephony_router
from app.modules.telephony.models import Call
from app.modules.users.models import Role, User
from tests.conftest import bearer, login, make_user

SECRET = "pbx-test-secret"


class FakeTranscriber:
    name = "fake-stt"

    async def transcribe(self, audio: Path, *, language: str | None = None) -> list[Segment]:
        if audio.name.startswith("operator"):
            return [
                Segment(0.0, 3.0, "Assalomu alaykum, Radeski klinikasi"),
                Segment(8.0, 11.0, "Sizga dushanba 10:00 yoki seshanba 15:00 qulaymi?"),
            ]
        return [Segment(4.0, 7.0, "Menga raqamim 90 000 22 44, soch to'kilishi bo'yicha")]


class FakeLlm:
    name = "fake-llm"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[type, Any] = {}
        self.fail = False

    async def parse(self, *, system: str, user: str, schema: type[BaseModel], cache_key: str):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.fail:
            raise LlmError("boom")
        return self.answers[schema]


def analysis_answer(**over: Any) -> AnalysisOut:
    data = {
        "conversation_type": "incoming",
        "language": "uz",
        "criteria": [
            {"code": "greeting", "passed": True, "comment": "ok"},
            {"code": "patient_name", "passed": False, "comment": "so'ramadi"},
            {"code": "need", "passed": True, "comment": "ok"},
            {"code": "two_slots", "passed": True, "comment": "ok"},
            {"code": "next_step", "passed": True, "comment": "ok"},
            {"code": "confirm", "passed": None, "comment": "yozilmadi"},
            {"code": "polite", "passed": True, "comment": "ok"},
            {"code": "closing", "passed": True, "comment": "ok"},
            {"code": "made_up", "passed": False, "comment": "unknown criterion is dropped"},
        ],
        "violations": [
            {"criterion": "patient_name", "quote": "Assalomu alaykum", "at": 0.0},
            {"criterion": "greeting", "quote": "not a violation (passed)", "at": 1.0},
        ],
        "red_flags": [{"code": "diagnosis", "quote": "bu alopesiya", "at": 9.0}],
        "summary": "Bemor soch to'kilishi bo'yicha qo'ng'iroq qildi, o'ylab ko'radi.",
        "outcome": "thinking",
        "reason": None,
        "extracted": Extracted(
            interest="trixolog", preferred_time="dushanba", source=None, next_step="juma kuni"
        ),
        "questions": ["Narxi qancha?"],
        "objections": ["Qimmat"],
    }
    return AnalysisOut.model_validate({**data, **over})


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeLlm:
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pbx_api_secret", SECRET)
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    monkeypatch.setattr(telephony_router, "_enqueue_recording", lambda cid: None)
    llm = FakeLlm()
    llm.answers[AnalysisOut] = analysis_answer()
    monkeypatch.setattr(ai, "get_transcriber", lambda: FakeTranscriber())
    monkeypatch.setattr(ai, "get_llm", lambda: llm)
    monkeypatch.setattr(qa, "get_llm", lambda: llm)
    monkeypatch.setattr("app.integrations.llm.get_llm", lambda: llm)

    def fake_split(stereo: Path, workdir: Path) -> dict[str, list[ai.Chunk]]:
        op, pt = workdir / "operator.mp3", workdir / "patient.mp3"
        op.write_bytes(b"x")
        pt.write_bytes(b"x")
        return {"operator": [(0.0, 12.0, op)], "patient": [(0.0, 12.0, pt)]}

    monkeypatch.setattr(ai, "split_channels", fake_split)
    return llm


async def answered_call(
    client: AsyncClient, pbx_id: str, *, talk: int = 60, task: str = "", recording: bool = True
) -> Call:
    now = int(systime.time())
    body = {
        "kind": "end", "direction": "out" if task else "in", "call_id": pbx_id,
        "caller": "900000001", "status": "answer" if task else "answered", "agent": "101",
        "started": now - talk - 5, "ended": now, "talk": talk, "task": task,
    }  # fmt: skip
    resp = await client.post(
        "/api/telephony/events", content=urlencode(body), headers={"X-PBX-Secret": SECRET}
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as s:
        call = (await s.scalars(select(Call).where(Call.pbx_id == pbx_id))).one()
        if recording:
            (Path(get_settings().recordings_dir) / f"{pbx_id}.mp3").write_bytes(b"ID3")
            call.recording, call.recording_status = f"{pbx_id}.mp3", "ready"
        await s.commit()
        return call


async def run_analysis(call_id: uuid.UUID) -> CallAnalysis | None:
    async with SessionLocal() as s:
        await seed_if_empty(s)  # the app seeds scripts at startup; tests start empty
        await ai.analyze_call(s, call_id)
        await s.commit()
        return await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))


async def operator_with_extension(username: str = "op1") -> User:
    await make_user(username, Role.OPERATOR)
    async with SessionLocal() as s:
        user = (await s.scalars(select(User).where(User.username == username))).one()
        user.sip_extension = "101"
        await s.commit()
        return user


def test_mask_pii_hides_numbers_but_keeps_times() -> None:
    assert mask_pii("raqamim +998 90 000-22-44, soat 10:30 da") == "raqamim [raqam], soat 10:30 da"
    assert mask_pii("pasport AB1234567") == "pasport AB[raqam]"
    assert mask_pii("2 ta vaqt: 15:00") == "2 ta vaqt: 15:00"
    # speech recognition punctuates dictated numbers; times next to them stay
    assert mask_pii("raqam 90, 000, 22, 44, soat 10:30") == "raqam [raqam], soat 10:30"
    assert mask_pii("90.000.22.44") == "[raqam]"
    assert mask_pii("karta 8600 0000 0000 0000") == "karta [raqam]"
    # prices are kept for the analysis
    assert mask_pii("narxi 1 500 000 so'm") == "narxi 1 500 000 so'm"


def test_speech_chunks_cut_out_silence() -> None:
    log = (
        "Duration: 00:01:00.00, start: 0.000000, bitrate: 256 kb/s\n"
        "[silencedetect] silence_start: 5.0\n[silencedetect] silence_end: 20.0 | d: 15\n"
        "[silencedetect] silence_start: 21.0\n[silencedetect] silence_end: 21.5 | d: 0.5\n"
        "[silencedetect] silence_start: 23.0\n[silencedetect] silence_end: 60.0 | d: 37\n"
    )
    speech = ai.speech_intervals(log)
    assert speech == [(0.0, 5.0), (20.0, 21.0), (21.5, 23.0)]
    # the short pause is kept inside one chunk; the 15 s silence is not sent to STT
    assert ai.plan_chunks(speech, 60.0) == [(0.0, 5.3), (19.7, 23.3)]
    # a 70 s monologue is split so timestamps stay useful
    assert ai.plan_chunks([(0.0, 70.0)], 70.0) == [(0.0, 30.0), (30.0, 60.0), (60.0, 70.0)]
    assert ai.speech_intervals("no duration here") == []


def test_score_uses_weights_and_skips_not_applicable() -> None:
    results = [
        {"code": "a", "passed": True},
        {"code": "b", "passed": False},
        {"code": "c", "passed": None},
    ]
    assert ai.score(results, {"a": 30, "b": 10, "c": 60}) == 75
    assert ai.score([{"code": "c", "passed": None}], {"c": 10}) is None


async def test_pipeline_transcribes_scores_and_flags(
    client: AsyncClient, clinic: dict, fakes: FakeLlm
) -> None:
    await operator_with_extension()
    call = await answered_call(client, "900.1")
    analysis = await run_analysis(call.id)

    assert analysis.status == "ready" and analysis.stt_model == "fake-stt"
    assert [s["ch"] for s in analysis.transcript] == ["operator", "patient", "operator"]
    # every active criterion once, unknown codes dropped; n/a excluded from the score
    assert [c["code"] for c in analysis.criteria][:2] == ["greeting", "patient_name"]
    assert "made_up" not in {c["code"] for c in analysis.criteria}
    assert analysis.score == 89  # 80 of 90 applicable weight points
    assert [v["criterion"] for v in analysis.violations] == ["patient_name"]
    assert analysis.has_red_flags and analysis.red_flags[0]["code"] == "diagnosis"
    assert analysis.suggested_outcome == "thinking" and analysis.conversation_type == "incoming"

    prompt = fakes.calls[0]
    assert "90 000 22 44" not in prompt["user"] and "[raqam]" in prompt["user"]
    assert "[4.0] P:" in prompt["user"] and "greeting" in prompt["system"]

    # idempotent: a second run doesn't call the model again
    await run_analysis(call.id)
    assert len(fakes.calls) == 1


async def test_prompt_carries_only_the_expected_scripts(
    client: AsyncClient, clinic: dict, fakes: FakeLlm
) -> None:
    await operator_with_extension()
    call = await answered_call(client, "900.2")  # inbound, no task
    await run_analysis(call.id)
    system = fakes.calls[0]["system"]
    assert "### incoming" in system and "### closing" in system
    assert "### laser" not in system and "- laser:" in system  # listed, not spelled out


async def test_daily_budget_stops_new_analyses(
    client: AsyncClient, clinic: dict, fakes: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.integrations import openai_client

    await operator_with_extension()
    monkeypatch.setattr(get_settings(), "ai_daily_budget_usd", 0.5)
    await openai_client.add_spend(0.6)
    call = await answered_call(client, "900.3")
    analysis = await run_analysis(call.id)
    assert analysis.status == "pending" and "budget" in analysis.error
    assert analysis.attempts == 0 and fakes.calls == []  # nothing was sent, no attempt used

    monkeypatch.setattr(get_settings(), "ai_daily_budget_usd", 5.0)
    assert (await run_analysis(call.id)).status == "ready"


async def test_a_call_in_progress_is_not_analysed_twice(
    client: AsyncClient, clinic: dict, fakes: FakeLlm
) -> None:
    await operator_with_extension()
    call = await answered_call(client, "900.4")
    async with SessionLocal() as s:
        s.add(CallAnalysis(call_id=call.id, status="transcribing", attempts=1))
        await s.commit()
    assert (await run_analysis(call.id)).status == "transcribing"
    assert fakes.calls == []


async def test_short_disabled_and_failed_calls(
    client: AsyncClient, clinic: dict, fakes: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    short = await answered_call(client, "901.1", talk=5)
    assert (await run_analysis(short.id)).status == "skipped"

    fakes.fail = True
    failing = await answered_call(client, "901.2")
    failed = await run_analysis(failing.id)
    assert failed.status == "failed" and "boom" in failed.error and failed.attempts == 1
    assert failed.transcript  # kept: the retry only re-runs the LLM
    async with SessionLocal() as s:
        assert failing.id in await ai.pending_calls(s)

    no_recording = await answered_call(client, "901.3", recording=False)
    assert await run_analysis(no_recording.id) is None

    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    another = await answered_call(client, "901.4")
    assert await run_analysis(another.id) is None


async def test_operator_confirms_or_corrects_the_suggestion(
    client: AsyncClient, clinic: dict, fakes: FakeLlm
) -> None:
    await operator_with_extension()
    op = bearer(await login(client, "op1"))
    await client.post(
        "/api/tasks",
        json={"patient_id": clinic["patient"], "due_at": datetime.now(UTC).isoformat()},
        headers=op,
    )
    async with SessionLocal() as s:
        task = (await s.scalars(select(Task).where(Task.type == TaskType.CALLBACK))).one()
    call = await answered_call(client, "902.1", task=str(task.id))
    await run_analysis(call.id)

    [card] = [
        t for t in (await client.get("/api/tasks", headers=op)).json() if t["id"] == str(task.id)
    ]
    suggestion = card["ai_suggestion"]
    assert suggestion["outcome"] == "thinking" and suggestion["next_step"] == "juma kuni"

    resp = await client.post(
        f"/api/tasks/{task.id}/result",
        json={"outcome": "refused", "reason": "price", "analysis_id": suggestion["analysis_id"]},
        headers=op,
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as s:
        a = await s.get(CallAnalysis, uuid.UUID(suggestion["analysis_id"]))
    assert a.review == "corrected"
    assert a.corrections == {
        "outcome": {"ai": "thinking", "operator": "refused"},
        "reason": {"ai": None, "operator": "price"},
    }


async def test_qa_panel_and_access(client: AsyncClient, clinic: dict, fakes: FakeLlm) -> None:
    await operator_with_extension()
    await make_user("op2", Role.OPERATOR)
    await make_user("sup1", Role.SUPERVISOR)
    call = await answered_call(client, "903.1")
    await run_analysis(call.id)
    sup = bearer(await login(client, "sup1"))
    op1 = bearer(await login(client, "op1"))
    op2 = bearer(await login(client, "op2"))

    overview = (await client.get("/api/ai/qa/overview", headers=sup)).json()
    assert overview["analysed"] == 1 and overview["avg_score"] == 89
    assert overview["red_flags_open"] == 1 and overview["operators"][0]["red_flags"] == 1
    rates = {c["code"]: c["pass_rate"] for c in overview["criteria"]}
    assert rates["greeting"] == 100 and rates["patient_name"] == 0 and rates["confirm"] is None
    assert (await client.get("/api/ai/qa/overview", headers=op1)).status_code == 403

    flagged = (await client.get("/api/ai/qa/calls", params={"flagged": True}, headers=sup)).json()
    assert [c["call_id"] for c in flagged] == [str(call.id)] and flagged[0]["red_flags"] == [
        "diagnosis"
    ]

    assert (await client.get(f"/api/ai/calls/{call.id}", headers=op1)).status_code == 200
    assert (await client.get(f"/api/ai/calls/{call.id}", headers=op2)).status_code == 403
    detail = (await client.get(f"/api/ai/calls/{call.id}", headers=sup)).json()
    assert detail["summary"] and detail["transcript"][0]["ch"] == "operator"

    ack = await client.post(f"/api/ai/calls/{call.id}/flags-reviewed", headers=sup)
    assert ack.status_code == 204
    assert (await client.get("/api/ai/qa/overview", headers=sup)).json()["red_flags_open"] == 0


async def test_criteria_are_seeded_and_editable(client: AsyncClient) -> None:
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    criteria = (await client.get("/api/ai/criteria", headers=sup)).json()
    assert len(criteria) == 8 and criteria[0]["code"] == "greeting"
    polite = next(c for c in criteria if c["code"] == "polite")
    body = {
        **{k: polite[k] for k in ("name_uz", "name_ru", "description")},
        "weight": 40,
        "active": False,
    }
    resp = await client.put(f"/api/ai/criteria/{polite['id']}", json=body, headers=sup)
    assert resp.status_code == 200 and resp.json()["weight"] == 40
    async with SessionLocal() as s:
        assert "polite" not in {c.code for c in await ai.active_criteria(s)}


async def test_digest_and_brief(client: AsyncClient, clinic: dict, fakes: FakeLlm) -> None:
    await operator_with_extension()
    call = await answered_call(client, "904.1")
    await run_analysis(call.id)
    fakes.answers[qa.DigestOut] = qa.DigestOut(
        summary="Hafta yaxshi o'tdi.",
        top_questions=[qa.DigestTopic(text="Narxi qancha?", count=1)],
        objections=[],
        complaints=[],
        recommendations=["Ismini so'rashni eslatish"],
    )
    await make_user("sup1", Role.SUPERVISOR)
    sup = bearer(await login(client, "sup1"))
    async with SessionLocal() as s:
        digest = await qa.make_digest(s, date_to=datetime.now(UTC).date() + timedelta(days=1))
        await s.commit()
    assert digest.stats["calls_analysed"] == 1 and digest.stats["questions"] == ["Narxi qancha?"]
    assert digest.content["recommendations"] == ["Ismini so'rashni eslatish"]
    latest = (await client.get("/api/ai/digest", headers=sup)).json()
    assert latest["id"] == str(digest.id)

    fakes.answers[qa.BriefOut] = qa.BriefOut(text="Eski bemor, soch to'kilishi.")
    op = bearer(await login(client, "op1"))
    brief = (await client.get(f"/api/ai/patients/{clinic['patient']}/brief", headers=op)).json()
    assert brief == {"text": "Eski bemor, soch to'kilishi.", "ai": True}
    assert "Sinov Bemor" not in fakes.calls[-1]["user"]  # no names in the facts sent out


async def test_brief_without_ai_lists_the_facts(
    client: AsyncClient, clinic: dict, op: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    brief = (await client.get(f"/api/ai/patients/{clinic['patient']}/brief", headers=op)).json()
    assert brief["ai"] is False and "patient kind: legacy" in brief["text"]


async def test_ai_suggests_diagnosis_categories(client: AsyncClient, fakes: FakeLlm) -> None:
    async with SessionLocal() as s:
        for text in ("выпадение волос диффузное", "непонятная запись"):
            s.add(DiagnosisMapping(text=text, status=MappingStatus.PENDING))
        await s.commit()
    from app.modules.diagnoses.service import _AiBatch, _AiItem

    fakes.answers[_AiBatch] = _AiBatch(
        items=[_AiItem(n=1, category="alopecia_diffuse"), _AiItem(n=2, category=None)]
    )
    await make_user("doc1", Role.DOCTOR)
    doc = bearer(await login(client, "doc1"))
    resp = await client.post("/api/diagnoses/ai-suggest", headers=doc)
    assert resp.status_code == 200 and resp.json()["suggested"] == 1
    async with SessionLocal() as s:
        rows = {m.text: m for m in await s.scalars(select(DiagnosisMapping))}
    assert rows["выпадение волос диффузное"].status == "suggested"
    assert rows["выпадение волос диффузное"].method == "ai"
    assert rows["непонятная запись"].status == "pending"


async def test_task_status_unaffected_by_ai(
    client: AsyncClient, clinic: dict, fakes: FakeLlm
) -> None:
    """An analysis never closes or edits a task by itself (a human decides)."""
    await operator_with_extension()
    op = bearer(await login(client, "op1"))
    await client.post(
        "/api/tasks",
        json={"patient_id": clinic["patient"], "due_at": datetime.now(UTC).isoformat()},
        headers=op,
    )
    async with SessionLocal() as s:
        task = (await s.scalars(select(Task).where(Task.type == TaskType.CALLBACK))).one()
    call = await answered_call(client, "905.1", task=str(task.id))
    await run_analysis(call.id)
    async with SessionLocal() as s:
        assert (await s.get(Task, task.id)).status == TaskStatus.OPEN


def test_wer_normalises_uzbek_apostrophes_and_case() -> None:
    from app.modules.ai.benchmark import wer

    assert wer("Qo‘ng‘iroq uchun rahmat", "qo'ng'iroq uchun rahmat") == 0
    assert wer("bir ikki uch to'rt", "bir ikki to'rt besh") == 0.5  # 1 deletion + 1 insertion
    assert wer("", "") == 0 and wer("", "salom") == 1


def test_benchmark_pairs_audio_with_reference(tmp_path: Path) -> None:
    from app.modules.ai.benchmark import pairs

    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("salom", encoding="utf-8")
    (tmp_path / "b.mp3").write_bytes(b"x")  # no reference -> skipped
    assert [(p.name, ref) for p, ref in pairs(tmp_path)] == [("a.mp3", "salom")]
