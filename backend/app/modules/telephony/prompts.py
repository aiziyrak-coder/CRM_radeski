"""IVR voice prompts (telephony/sounds/README.md): each file says the text in Uzbek, then in
Russian. Generated with TTS by `python -m app.cli generate-prompts`, or recorded by a person."""

import asyncio
import subprocess
import tempfile
from pathlib import Path

from app.core import clinic_time
from app.integrations import tts

DAYS_UZ = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
DAYS_RU_FROM = [
    "понедельника",
    "вторника",
    "среды",
    "четверга",
    "пятницы",
    "субботы",
    "воскресенья",
]
DAYS_RU_TO = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
# numbers are spelled out: TTS reads "8 dan" in Uzbek unreliably
HOURS_UZ = {
    7: "yetti", 8: "sakkiz", 9: "to'qqiz", 10: "o'n", 16: "o'n olti", 17: "o'n yetti",
    18: "o'n sakkiz", 19: "o'n to'qqiz", 20: "yigirma",
}  # fmt: skip
HOURS_RU = {
    7: "семи", 8: "восьми", 9: "девяти", 10: "десяти", 16: "шестнадцати", 17: "семнадцати",
    18: "восемнадцати", 19: "девятнадцати", 20: "двадцати",
}  # fmt: skip


def _hours() -> tuple[str, str]:
    days = sorted(clinic_time.WORKDAYS)
    first, last = days[0], days[-1]
    opens, closes = clinic_time.OPEN.hour, clinic_time.CLOSE.hour
    o_uz, c_uz = HOURS_UZ.get(opens, str(opens)), HOURS_UZ.get(closes, str(closes))
    o_ru, c_ru = HOURS_RU.get(opens, str(opens)), HOURS_RU.get(closes, str(closes))
    uz = f"Klinika {DAYS_UZ[first]}dan {DAYS_UZ[last]}gacha, soat {o_uz}dan {c_uz}gacha ishlaydi."
    ru = (
        f"Клиника работает с {DAYS_RU_FROM[first]} по {DAYS_RU_TO[last]}, с {o_ru} до {c_ru} часов."
    )
    return uz, ru


def texts() -> dict[str, tuple[str, str]]:
    """file name -> (Uzbek, Russian)."""
    hours_uz, hours_ru = _hours()
    return {
        # short: the caller hears it before reaching an operator (the queue music follows)
        "welcome": (
            "Assalomu alaykum, Radeski Skin Clinic. Suhbat sifat nazorati uchun yozib olinadi.",
            "Здравствуйте, Radeski Skin Clinic. Разговор записывается для контроля качества.",
        ),
        # followed by press-1-callback in the dialplan (extensions.conf, "offer")
        "after-hours": (
            f"Assalomu alaykum, Radeski Skin Clinic. {hours_uz}",
            f"Здравствуйте, Radeski Skin Clinic. {hours_ru}",
        ),
        "press-1-callback": (
            "Sizga qayta qo'ng'iroq qilishimizni xohlasangiz, bir raqamini bosing.",
            "Если хотите, чтобы мы вам перезвонили, нажмите единицу.",
        ),
        "callback-ok": (
            "Rahmat, operatorimiz sizga tez orada qo'ng'iroq qiladi.",
            "Спасибо, наш оператор скоро вам перезвонит.",
        ),
        "goodbye": (
            "Katta rahmat. Salomat bo'ling, xayr.",
            "Спасибо за звонок. Будьте здоровы.",
        ),
    }


def to_asterisk(parts: list[bytes], target: Path, pause: float = 0.6) -> None:
    """Joins the language versions with a short pause -> WAV 8 kHz mono 16-bit for Asterisk."""
    with tempfile.TemporaryDirectory() as tmp:
        inputs: list[str] = []
        for i, audio in enumerate(parts):
            path = Path(tmp) / f"{i}.wav"
            path.write_bytes(audio)
            inputs += ["-i", str(path)]
        n = len(parts)
        chains = [f"[{i}:a]aresample=8000,aformat=channel_layouts=mono[a{i}]" for i in range(n)]
        pad = f"[a0]apad=pad_dur={pause}[p0]"
        joined = "[p0]" + "".join(f"[a{i}]" for i in range(1, n)) + f"concat=n={n}:v=0:a=1[out]"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *inputs,
             "-filter_complex", ";".join([*chains, pad, joined]),
             "-map", "[out]", "-ar", "8000", "-ac", "1", "-sample_fmt", "s16", str(target)],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip


async def generate(out_dir: Path, voice: str = "nova", only: list[str] | None = None) -> list[Path]:
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    written = []
    for name, (uz, ru) in texts().items():
        if only and name not in only:
            continue
        parts = [await tts.synthesize(uz, "uz", voice), await tts.synthesize(ru, "ru", voice)]
        target = out_dir / f"{name}.wav"
        await asyncio.to_thread(to_asterisk, parts, target)
        written.append(target)
    return written
