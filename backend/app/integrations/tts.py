"""Text-to-speech for the IVR voice prompts (telephony/sounds/README.md). Used once, offline, by
`python -m app.cli generate-prompts`; the result is checked by a person before it goes live."""

from app.integrations.openai_client import add_spend, client, ensure_budget

TTS_MODEL = "gpt-4o-mini-tts"
TTS_USD_PER_MINUTE = 0.015  # OpenAI's estimate for gpt-4o-mini-tts

INSTRUCTIONS = {
    "uz": "Speak Uzbek (Latin script text) with natural Uzbek pronunciation. You are the calm, "
    "friendly receptionist of a medical skin clinic. Moderate pace, clear diction.",
    "ru": "Speak Russian with natural pronunciation. You are the calm, friendly receptionist of "
    "a medical skin clinic. Moderate pace, clear diction.",
}


async def synthesize(text: str, language: str, voice: str = "nova") -> bytes:
    """WAV bytes (24 kHz); the caller converts them for Asterisk."""
    await ensure_budget()
    response = await client().audio.speech.create(
        model=TTS_MODEL,
        voice=voice,
        input=text,
        instructions=INSTRUCTIONS[language],
        response_format="wav",
    )
    audio = response.content
    # 24 kHz 16-bit mono: bytes -> seconds, for today's AI spend
    await add_spend(TTS_USD_PER_MINUTE * len(audio) / (24000 * 2) / 60)
    return audio
