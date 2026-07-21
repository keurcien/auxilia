"""Middleware that stamps the current date and time onto the system prompt.

Agent instructions are static; the model has no notion of "now". This
middleware appends the current UTC date and time to the end of the system
prompt on every model call, so the timestamp stays fresh across a whole run
(triggers, durable runs) instead of being frozen at agent-build time.
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


class CurrentDatetimeMiddleware(AgentMiddleware):
    """Append the current UTC date/time to the system prompt on each model call."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        now = datetime.now(UTC).strftime("%A, %B %d, %Y, %H:%M UTC")
        stamp = f"Current date and time: {now}"
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
