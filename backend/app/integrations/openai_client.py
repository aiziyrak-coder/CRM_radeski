"""One shared async OpenAI client (the key lives in .env as OPENAI_API_KEY)."""

from functools import lru_cache

from openai import AsyncOpenAI

from app.core.config import get_settings


class AiDisabledError(RuntimeError):
    """OPENAI_API_KEY is not set."""


@lru_cache
def client() -> AsyncOpenAI:
    key = get_settings().openai_api_key
    if not key:
        raise AiDisabledError("OPENAI_API_KEY is empty")
    # the SDK retries 429/5xx with backoff on its own
    return AsyncOpenAI(api_key=key, max_retries=3, timeout=180)


def enabled() -> bool:
    return bool(get_settings().openai_api_key)
