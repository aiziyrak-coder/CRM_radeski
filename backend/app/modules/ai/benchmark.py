"""STT benchmark (plan 4.1): which transcription model understands the clinic's calls best.

Put recordings (mp3/wav, one speaker channel or mixed) and a hand-made reference transcript with
the same name (`call01.mp3` + `call01.txt`) into one folder, then:

    python -m app.cli stt-benchmark --dir /data/stt --models gpt-4o-transcribe,whisper-1

The folder is outside git (real voices are personal data).
"""

import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.stt.openai_stt import OpenAITranscriber

AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".webm"}
# USD per audio minute, for the report only (check openai.com/pricing before deciding)
PRICE_PER_MIN = {
    "whisper-1": 0.006,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-transcribe-diarize": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
}

# Uzbek apostrophe variants (o‘ o' oʻ o`) and Cyrillic/Latin case are normalised before comparing
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).translate(_APOSTROPHES).lower()
    return re.findall(r"[\w']+", text)


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: (substitutions + deletions + insertions) / reference words."""
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


@dataclass
class ModelResult:
    model: str
    files: int = 0
    wer_sum: float = 0.0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def wer(self) -> float | None:
        return self.wer_sum / self.files if self.files else None


def pairs(folder: Path) -> list[tuple[Path, str]]:
    out = []
    for audio in sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO):
        ref = audio.with_suffix(".txt")
        if ref.exists():
            out.append((audio, ref.read_text(encoding="utf-8")))
    return out


async def run(folder: Path, models: list[str], language: str | None = None) -> list[ModelResult]:
    samples = pairs(folder)
    results = []
    for model in models:
        result = ModelResult(model)
        stt = OpenAITranscriber(model)
        for audio, reference in samples:
            started = time.monotonic()
            try:
                segments = await stt.transcribe(audio, language=language)
            except Exception as exc:  # report and go on with the next file
                result.errors.append(f"{audio.name}: {exc}")
                continue
            result.seconds += time.monotonic() - started
            result.files += 1
            result.wer_sum += wer(reference, " ".join(s.text for s in segments))
        results.append(result)
    return results
