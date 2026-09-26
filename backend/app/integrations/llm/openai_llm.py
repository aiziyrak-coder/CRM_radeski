import logging
from typing import TypeVar

from openai import APIError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.integrations.llm import LlmError
from app.integrations.openai_client import (
    AiDisabledError,
    add_spend,
    client,
    ensure_budget,
    llm_cost,
)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAILlm:
    """Responses API with structured outputs (strict JSON schema from the Pydantic model).

    The long, unchanging instructions go first so OpenAI's automatic prompt caching reuses them;
    `cache_key` groups requests that share that prefix. Requests go to the flex tier (half
    price) when `AI_SERVICE_TIER=flex`; if flex has no capacity right now, the request is repeated
    once at the standard tier. Every response's cost is added to today's AI spend.
    """

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.name = model or settings.ai_llm_model
        self.effort = settings.ai_reasoning_effort
        self.tier = settings.ai_service_tier or None

    async def parse(self, *, system: str, user: str, schema: type[T], cache_key: str) -> T:
        try:
            await ensure_budget()
        except AiDisabledError as exc:
            raise LlmError(str(exc)) from exc
        kwargs: dict = {}
        if self.effort:
            kwargs["reasoning"] = {"effort": self.effort}
        last: Exception | None = None
        tier = self.tier
        for _ in range(2):  # one retry when the output doesn't validate
            try:
                response = await self._create(system, user, schema, cache_key, tier, kwargs)
            except RateLimitError as exc:
                if tier != "flex":
                    raise LlmError(f"openai: {exc}") from exc
                log.info("flex tier unavailable, retrying at the standard tier: %s", exc)
                tier = None
                try:
                    response = await self._create(system, user, schema, cache_key, tier, kwargs)
                except (APIError, ValidationError) as exc2:
                    raise LlmError(f"openai: {exc2}") from exc2
            except ValidationError as exc:
                last = exc
                continue
            except APIError as exc:
                raise LlmError(f"openai: {exc}") from exc
            if response.status == "incomplete":
                reason = getattr(response.incomplete_details, "reason", None)
                raise LlmError(f"incomplete response: {reason}")
            for item in response.output:
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) == "refusal":
                        raise LlmError(f"refusal: {part.refusal}")
            if response.output_parsed is not None:
                return response.output_parsed
            last = LlmError("empty structured output")
        raise LlmError(str(last))

    async def _create(self, system, user, schema, cache_key, tier, kwargs):
        if tier:
            kwargs = {**kwargs, "service_tier": tier}
        response = await client().responses.parse(
            model=self.name,
            instructions=system,
            input=user,
            text_format=schema,
            prompt_cache_key=cache_key,
            max_output_tokens=get_settings().ai_max_output_tokens,
            **kwargs,
        )
        await add_spend(
            llm_cost(self.name, response.usage, getattr(response, "service_tier", tier))
        )
        return response
