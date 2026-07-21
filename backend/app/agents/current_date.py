"""Middleware that stamps a fixed date onto the system prompt.

Agent instructions are static; the model has no notion of "now". This
middleware appends a date to the end of the system prompt on every model
call, giving the model temporal grounding.

The date is frozen at construction — callers pass the thread's creation
date — so the system prompt never changes for the thread's lifetime. The
system prompt heads the provider's prompt-cache prefix, and some providers
(DeepSeek) keep that cache warm for days: any mutation, even at day
granularity, would invalidate the cache for the whole conversation.
Trade-off: a thread resumed days later still shows its creation date.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage


class CurrentDateMiddleware(AgentMiddleware):
    """Append a fixed (thread-creation) date to the system prompt."""

    def __init__(self, date: datetime) -> None:
        super().__init__()
        self.stamp = f"Current date: {date.strftime('%A, %B %d, %Y')} (UTC)"

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        message = request.system_message
        if message is None:
            stamped = SystemMessage(content=self.stamp)
        elif isinstance(message.content, str):
            stamped = SystemMessage(content=f"{message.content}\n\n{self.stamp}")
        else:
            # Content-block form (subagent compile path): append a text block
            # so the existing block shape is preserved.
            stamped = SystemMessage(
                content=[*message.content, {"type": "text", "text": self.stamp}]
            )
        return await handler(request.override(system_message=stamped))
