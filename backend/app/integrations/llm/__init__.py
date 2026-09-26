"""LLM adapters: structured output only (the answer must validate against a Pydantic model)."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """The model refused, ran out of tokens or returned something that isn't the schema."""


class StructuredLlm(Protocol):
    name: str

    async def parse(self, *, system: str, user: str, schema: type[T], cache_key: str) -> T: ...


def get_llm() -> StructuredLlm:
    from app.integrations.llm.openai_llm import OpenAILlm

    return OpenAILlm()
