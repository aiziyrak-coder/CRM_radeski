"""One shared async OpenAI client (the key lives in .env as OPENAI_API_KEY) and the daily spend
guard: every request's cost is added to a per-clinic-day counter in Redis, and nothing new is
sent once `AI_DAILY_BUDGET_USD` is used up (it resumes the next day)."""

import logging
from functools import lru_cache

from openai import AsyncOpenAI
from redis.asyncio import Redis

from app.core import clinic_time
from app.core.config import get_settings

log = logging.getLogger(__name__)


class AiDisabledError(RuntimeError):
    """OPENAI_API_KEY is not set."""


class AiBudgetExceededError(AiDisabledError):
    """Today's AI budget is used up."""


@lru_cache
def client() -> AsyncOpenAI:
    key = get_settings().openai_api_key
    if not key:
        raise AiDisabledError("OPENAI_API_KEY is empty")
    # the SDK retries 429/5xx/timeouts with backoff on its own; flex requests can take minutes.
    # Worst case per request ~(1 + 2) x 300 s, far below ai.service.STUCK_AFTER
    return AsyncOpenAI(api_key=key, max_retries=2, timeout=300)


def enabled() -> bool:
    return bool(get_settings().openai_api_key)


# --- cost -------------------------------------------------------------------------------------

# USD per 1M tokens (input, cached input, output) at standard rates; flex/batch is half.
# Unknown models are priced as the most expensive row so the budget errs on the safe side.
LLM_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
}
_FALLBACK_LLM = (2.50, 0.25, 15.00)
# USD per audio minute
STT_PRICES: dict[str, float] = {
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-transcribe": 0.0045,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-transcribe-diarize": 0.006,
    "whisper-1": 0.006,
}


def _base(model: str) -> str:
    # dated snapshots ("gpt-5.4-mini-2026-03-17") cost the same as the alias
    return max((m for m in LLM_PRICES if model.startswith(m)), key=len, default=model)


def llm_cost(model: str, usage: object, service_tier: str | None) -> float:
    if usage is None:
        return 0.0
    price_in, price_cached, price_out = LLM_PRICES.get(_base(model), _FALLBACK_LLM)
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    details = getattr(usage, "input_tokens_details", None)
    cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    usd = ((tokens_in - cached) * price_in + cached * price_cached + tokens_out * price_out) / 1e6
    return usd / 2 if service_tier in ("flex", "batch") else usd


def stt_cost(model: str, seconds: float) -> float:
    base = max((m for m in STT_PRICES if model.startswith(m)), key=len, default="")
    return STT_PRICES.get(base, 0.006) * seconds / 60


def _key() -> str:
    return f"ai:spend:{clinic_time.today().isoformat()}"


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def add_spend(usd: float) -> None:
    if usd <= 0:
        return
    redis = _redis()
    try:
        await redis.incrbyfloat(_key(), usd)
        await redis.expire(_key(), 40 * 86400)
    except Exception:  # accounting must never break the request that already happened
        log.exception("could not record AI spend")
    finally:
        await redis.aclose()


async def spent_today() -> float:
    redis = _redis()
    try:
        return float(await redis.get(_key()) or 0)
    except Exception:
        log.exception("could not read AI spend")
        return 0.0
    finally:
        await redis.aclose()


async def ensure_budget() -> None:
    """Raise before sending anything new when AI is off or today's budget is used up."""
    if not enabled():
        raise AiDisabledError("OPENAI_API_KEY is empty")
    budget = get_settings().ai_daily_budget_usd
    if budget > 0 and await spent_today() >= budget:
        raise AiBudgetExceededError(f"daily AI budget of ${budget:g} is used up")


async def available() -> bool:
    try:
        await ensure_budget()
    except AiDisabledError:
        return False
    return True
