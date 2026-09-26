"""In-process domain events (ARXITEKTURA 4.1).

Services emit events inside their transaction; subscribers (e.g. task rules) run in the same
session, so an event and its consequences commit or roll back together.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[Handler]] = defaultdict(list)


def on(event: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        _handlers[event].append(handler)
        return handler

    return register


async def emit(session: AsyncSession, event: str, **payload: Any) -> None:
    for handler in _handlers[event]:
        await handler(session, payload)
