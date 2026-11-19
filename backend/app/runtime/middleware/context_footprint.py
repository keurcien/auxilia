"""Record what each model request is made of.

Providers report one input total per call. This middleware sits innermost in
the stack, so it sees the request exactly as it is sent (the system prompt
with every harness fragment, the tool schemas left after discovery, the
conversation), estimates each part, scales the estimates to the
provider-reported total and stores the breakdown on the response's
``response_metadata[FOOTPRINT_KEY]``. The composer's context gauge reads it
from the last AI message.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool


logger = logging.getLogger(__name__)

FOOTPRINT_KEY = "context_footprint"


def _tool_name(tool: BaseTool | dict[str, Any]) -> str | None:
    if isinstance(tool, BaseTool):
        return tool.name
    name = tool.get("name")
    return name if isinstance(name, str) else None


def _context_window(model: Any) -> int | None:
    profile = getattr(model, "profile", None)
    window = profile.get("max_input_tokens") if isinstance(profile, dict) else None
    return window if isinstance(window, int) and window > 0 else None


def _response_message(response: ModelResponse | AIMessage) -> AIMessage | None:
    if isinstance(response, AIMessage):
        return response
    result = getattr(response, "result", None)
    if not isinstance(result, list):
        return None
    return next(
        (message for message in reversed(result) if isinstance(message, AIMessage)),
        None,
    )


class ContextFootprintMiddleware(AgentMiddleware):
    """Attach the request's token breakdown to the model's answer.

    ``searchable_tools`` are the tools discovery may hide: the ones missing
    from a request count as available but not loaded, so the footprint shows
    what loading everything would have cost.
    """

    def __init__(self, searchable_tools: Sequence[BaseTool] = ()) -> None:
        super().__init__()
        self.searchable_tools = {tool.name: tool for tool in searchable_tools}
        self._tool_tokens: dict[str, int] = {}

    def _tool_cost(self, tool: BaseTool | dict[str, Any]) -> int:
        name = tool.name if isinstance(tool, BaseTool) else None
        if name is not None and name in self._tool_tokens:
            return self._tool_tokens[name]
        cost = count_tokens_approximately([], tools=[tool])
        if name is not None:
            self._tool_tokens[name] = cost
        return cost

    def _estimate(self, request: ModelRequest) -> dict[str, int]:
        loaded = list(request.tools)
        loaded_names = {_tool_name(tool) for tool in loaded}
        hidden = [
            tool
            for name, tool in self.searchable_tools.items()
            if name not in loaded_names
        ]
        return {
            "system": (
                count_tokens_approximately([request.system_message])
                if request.system_message is not None
                else 0
            ),
            "tools": sum(self._tool_cost(tool) for tool in loaded),
            "messages": count_tokens_approximately(request.messages),
            "tools_hidden": sum(self._tool_cost(tool) for tool in hidden),
            "tools_loaded": len(loaded),
            "tools_available": len(loaded) + len(hidden),
        }

    @staticmethod
    def _footprint(
        estimate: dict[str, int], message: AIMessage, window: int | None
    ) -> dict[str, Any]:
        estimated_total = estimate["system"] + estimate["tools"] + estimate["messages"]
        usage = message.usage_metadata
        reported = usage["input_tokens"] if usage else 0
        measured = reported > 0 and estimated_total > 0
        total = reported if measured else estimated_total
        scale = total / estimated_total if estimated_total else 1.0
        system = round(estimate["system"] * scale)
        tools = round(estimate["tools"] * scale)
        return {
            "context_window": window,
            "input_tokens": total,
            "measured": measured,
            "system": system,
            "tools": tools,
            "messages": max(0, total - system - tools),
            "tools_loaded": estimate["tools_loaded"],
            "tools_available": estimate["tools_available"],
            "tools_hidden": round(estimate["tools_hidden"] * scale),
        }

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        try:
            estimate = self._estimate(request)
        except Exception:  # noqa: BLE001 — a metric must never fail the call
            logger.debug("Context footprint estimate failed", exc_info=True)
            return await handler(request)
        response = await handler(request)
        message = _response_message(response)
        if message is not None:
            message.response_metadata[FOOTPRINT_KEY] = self._footprint(
                estimate, message, _context_window(request.model)
            )
        return response
