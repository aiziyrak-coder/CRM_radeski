from pathlib import Path

from app.core.config import get_settings
from app.integrations.openai_client import client
from app.integrations.stt import Segment

# vocabulary hint for models that accept a prompt (clinic, specialties, common services)
VOCABULARY = (
    "Radeski Skin Clinic, dermatolog, trixolog, kosmetolog, lazer epilyatsiya, akne, psoriaz, "
    "vitiligo, alopesiya, konsultatsiya, qabul, Farg'ona, Qo'qon. "
    "Дерматолог, трихолог, косметолог, лазерная эпиляция, консультация, запись."
)


class OpenAITranscriber:
    """OpenAI transcription. Timestamps come from `diarized_json` (gpt-4o-transcribe-diarize) or
    `verbose_json` (whisper-1); other models return plain text as a single segment."""

    def __init__(self, model: str | None = None) -> None:
        self.name = model or get_settings().ai_stt_model

    async def transcribe(self, audio: Path, *, language: str | None = None) -> list[Segment]:
        kwargs: dict = {"model": self.name}
        if language:
            kwargs["language"] = language
        if "diarize" in self.name:
            kwargs |= {"response_format": "diarized_json", "chunking_strategy": "auto"}
        elif self.name.startswith("whisper"):
            kwargs |= {
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment"],
                "prompt": VOCABULARY,
            }
        else:
            kwargs |= {"response_format": "json", "prompt": VOCABULARY}
        with audio.open("rb") as f:
            result = await client().audio.transcriptions.create(file=f, **kwargs)
        segments = getattr(result, "segments", None)
        if segments:
            return [
                Segment(float(s.start), float(s.end), s.text.strip())
                for s in segments
                if s.text and s.text.strip()
            ]
        text = (getattr(result, "text", "") or "").strip()
        duration = float(getattr(result, "duration", 0) or 0)
        return [Segment(0.0, duration, text)] if text else []
