"""Middleware that stamps the current date onto the system prompt.

Agent instructions are static; the model has no notion of "now". This
middleware appends the current UTC date to the end of the system prompt on
every model call, so a thread resumed days later still sees today's date.

Deliberately date-only (no time of day): the system prompt sits at the front
of the provider's prompt-cache prefix, so any value that changes between
calls would invalidate the cache for the whole conversation on every turn.
A day-granularity stamp keeps the prompt byte-identical within a day.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage


class CurrentDateMiddleware(AgentMiddleware):
    """Append the current UTC date to the system prompt on each model call."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        today = datetime.now(UTC).strftime("%A, %B %d, %Y")
        stamp = f"Current date: {today} (UTC)"
        message = request.system_message
        if message is None:
            stamped = SystemMessage(content=stamp)
        elif isinstance(message.content, str):
            stamped = SystemMessage(content=f"{message.content}\n\n{stamp}")
        else:
            # Content-block form (subagent compile path): append a text block
            # so the existing block shape is preserved.
            stamped = SystemMessage(
                content=[*message.content, {"type": "text", "text": stamp}]
            )
        return await handler(request.override(system_message=stamped))
