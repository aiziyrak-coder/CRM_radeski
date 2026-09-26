"""Speech-to-text adapters. The rest of the app only sees `Segment` lists."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Segment:
    start: float  # seconds from the start of the file
    end: float
    text: str


class Transcriber(Protocol):
    name: str

    async def transcribe(self, audio: Path, *, language: str | None = None) -> list[Segment]: ...


def get_transcriber() -> Transcriber:
    from app.integrations.stt.openai_stt import OpenAITranscriber

    return OpenAITranscriber()
