"""The OpenAI adapters against a fake HTTP transport: request shape and response parsing."""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.integrations.llm import LlmError, openai_llm
from app.integrations.stt import openai_stt


def fake_client(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class Answer(BaseModel):
    summary: str
    score: int | None


def response_json(text: str, status: str = "completed") -> dict:
    return {
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-test",
        "status": status, "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{
            "type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
    }  # fmt: skip


async def test_llm_sends_strict_schema_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=response_json('{"summary": "ok", "score": 7}'))

    monkeypatch.setattr(openai_llm, "client", lambda: fake_client(handler))
    llm = openai_llm.OpenAILlm(model="gpt-test")
    out = await llm.parse(system="be brief", user="hello", schema=Answer, cache_key="k1")

    assert out == Answer(summary="ok", score=7)
    assert seen["model"] == "gpt-test" and seen["instructions"] == "be brief"
    assert seen["input"] == "hello" and seen["prompt_cache_key"] == "k1"
    fmt = seen["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert set(fmt["schema"]["required"]) == {"summary", "score"}
    assert seen["reasoning"] == {"effort": "low"}


async def test_llm_reports_cut_off_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def truncated(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_json('{"summary": "o', "incomplete"))

    def empty(request: httpx.Request) -> httpx.Response:
        body = response_json("", "incomplete")
        body["output"] = []  # ran out of tokens while reasoning
        return httpx.Response(200, json=body)

    llm = openai_llm.OpenAILlm(model="gpt-test")
    monkeypatch.setattr(openai_llm, "client", lambda: fake_client(truncated))
    with pytest.raises(LlmError, match="Invalid JSON"):
        await llm.parse(system="s", user="u", schema=Answer, cache_key="k")
    assert len(requests) == 2  # one retry, then give up

    monkeypatch.setattr(openai_llm, "client", lambda: fake_client(empty))
    with pytest.raises(LlmError, match="max_output_tokens"):
        await llm.parse(system="s", user="u", schema=Answer, cache_key="k")


async def test_llm_wraps_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_llm,
        "client",
        lambda: fake_client(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})),
    )
    with pytest.raises(LlmError, match="bad key"):
        await openai_llm.OpenAILlm(model="gpt-test").parse(
            system="s", user="u", schema=Answer, cache_key="k"
        )


async def test_diarized_transcription(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "task": "transcribe", "duration": 4.2, "text": "salom. qalaysiz",
                "segments": [
                    {"type": "transcript.text.segment", "id": "a", "start": 0.0, "end": 1.5,
                     "text": " salom.", "speaker": "A"},
                    {"type": "transcript.text.segment", "id": "b", "start": 2.0, "end": 4.2,
                     "text": "qalaysiz ", "speaker": "A"},
                ],
            },
        )  # fmt: skip

    monkeypatch.setattr(openai_stt, "client", lambda: fake_client(handler))
    audio = tmp_path / "operator.mp3"
    audio.write_bytes(b"ID3")
    segments = await openai_stt.OpenAITranscriber("gpt-4o-transcribe-diarize").transcribe(audio)

    assert [(s.start, s.end, s.text) for s in segments] == [
        (0.0, 1.5, "salom."),
        (2.0, 4.2, "qalaysiz"),
    ]
    assert "diarized_json" in seen["body"] and "gpt-4o-transcribe-diarize" in seen["body"]


async def test_plain_transcription_is_one_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        openai_stt,
        "client",
        lambda: fake_client(lambda r: httpx.Response(200, json={"text": " salom "})),
    )
    audio = tmp_path / "patient.mp3"
    audio.write_bytes(b"ID3")
    segments = await openai_stt.OpenAITranscriber("gpt-4o-transcribe").transcribe(audio)
    assert [s.text for s in segments] == ["salom"]


@pytest.mark.parametrize("schema", ["analysis", "digest", "brief", "diagnoses"])
def test_our_schemas_are_valid_strict_schemas(schema: str) -> None:
    """OpenAI's strict mode rejects some schemas (open dicts, defaults); catch that in CI."""
    from openai.lib._pydantic import to_strict_json_schema

    from app.modules.ai.prompts import AnalysisOut
    from app.modules.ai.qa import BriefOut, DigestOut
    from app.modules.diagnoses.service import _AiBatch

    model = {"analysis": AnalysisOut, "digest": DigestOut, "brief": BriefOut, "diagnoses": _AiBatch}
    result = to_strict_json_schema(model[schema])

    def check(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(result)
