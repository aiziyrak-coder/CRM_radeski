import logging
from typing import TypeVar

from openai import APIError
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.integrations.llm import LlmError
from app.integrations.openai_client import client

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAILlm:
    """Responses API with structured outputs (strict JSON schema from the Pydantic model).

    The long, unchanging instructions go first so OpenAI's automatic prompt caching reuses them;
    `cache_key` groups requests that share that prefix.
    """

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.name = model or settings.ai_llm_model
        self.effort = settings.ai_reasoning_effort

    async def parse(self, *, system: str, user: str, schema: type[T], cache_key: str) -> T:
        kwargs: dict = {}
        if self.effort:
            kwargs["reasoning"] = {"effort": self.effort}
        last: Exception | None = None
        for _ in range(2):  # one retry when the output doesn't validate
            try:
                response = await client().responses.parse(
                    model=self.name,
                    instructions=system,
                    input=user,
                    text_format=schema,
                    prompt_cache_key=cache_key,
                    max_output_tokens=get_settings().ai_max_output_tokens,
                    **kwargs,
                )
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
