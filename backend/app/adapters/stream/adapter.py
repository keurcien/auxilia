

"""
Adapter for converting LangGraph/LangChain event streams to the AI SDK v5 streaming protocol.

This is the main entry point. It routes incoming LangGraph events to focused handlers
and manages the overall stream lifecycle (start → content/tools → finish).

Usage:
    adapter = AISDKStreamAdapter()
    async for sse_event in adapter.stream(langgraph_event_stream):
        yield sse_event
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from .content_stream import ContentStreamManager
from .handlers import (
    handle_chat_model_end,
    handle_chat_model_stream,
    handle_interrupt,
    handle_tool_end,
    handle_tool_start,
)
from .sse import SSE_DONE, format_sse_event
from .tool_tracker import ToolCallTracker

logger = logging.getLogger(__name__)


class AISDKStreamAdapter:
    """
    Converts a LangGraph async event stream into AI SDK v5 Server-Sent Events.

    Responsibilities (orchestration only):
    - Lifecycle: emits start/finish/done framing
    - Routing: dispatches each event type to the appropriate handler
    - Error boundary: catches and surfaces stream errors

    All content logic lives in ContentStreamManager.
    All tool logic lives in ToolCallTracker + handlers.
    """

    def __init__(
        self,
        message_id: str | None = None,
        is_resume: bool = False,
        rejected_tool_calls: list[dict] | None = None,
        approved_tool_call_ids: list[str] | None = None,
    ):
        self._message_id = message_id or str(uuid.uuid4())
        self._is_resuming = is_resume

        self._rejected_tool_calls = rejected_tool_calls or []

        # Build the full set of pre-approved IDs (explicit approvals + rejections both count
        # as "already handled" from the streaming perspective)
        pre_approved = set(approved_tool_call_ids or [])
        pre_approved.update(r["toolCallId"] for r in self._rejected_tool_calls)

        self._content = ContentStreamManager()
        self._tools = ToolCallTracker(pre_approved_ids=pre_approved)

        self._approval_pending = False
        self._finished = False

    async def stream(self, events: AsyncGenerator[Any, None]) -> AsyncGenerator[str, None]:
        """
        Main entry point. Consumes a LangGraph event stream and yields SSE strings.
        """
        yield format_sse_event("start", messageId=self._message_id)

        # Replay rejection results for previously-rejected tool calls
        for rejected in self._rejected_tool_calls:
            yield format_sse_event(
                "tool-output-error",
                toolCallId=rejected["toolCallId"],
                errorText=rejected.get(
                    "reason", "Tool execution was rejected by user"),
            )

        try:
            async for value in events:
                if not isinstance(value, dict) or "event" not in value:
                    continue

                async for sse_event in self._route_event(value):
                    yield sse_event

        except Exception as e:
            logger.exception("Stream processing error")
            yield format_sse_event("error", errorText=f"Stream processing error: {str(e)}")
            for event in self._finish():
                yield event
            return

        for event in self._finish():
            yield event

    async def _route_event(self, value: dict[str, Any]) -> AsyncGenerator[str, None]:
        """Dispatch a single LangGraph event to the appropriate handler."""
        event_type = value["event"]

        if event_type == "error":
            error_msg = value.get("data", {}).get("error", "Unknown error")
            yield format_sse_event("error", errorText=error_msg)
            for event in self._finish():
                yield event

        elif event_type == "on_chat_model_stream":
            chunk = value.get("data", {}).get("chunk")
            async for event in handle_chat_model_stream(chunk, self._content, self._tools):
                yield event

        elif event_type == "on_chat_model_end":
            async for event in handle_chat_model_end(value, self._tools):
                yield event

        elif event_type == "on_tool_start":
            async for event in handle_tool_start(value, self._content, self._tools):
                yield event

        elif event_type == "on_tool_end":
            async for event in handle_tool_end(value, self._tools):
                yield event

        elif event_type == "on_chain_start":
            self._detect_resume(value)

        elif event_type == "on_chain_stream":
            has_approvals = False
            async for event in handle_interrupt(value, self._tools):
                has_approvals = True
                yield event
            if has_approvals:
                self._approval_pending = True

    def _detect_resume(self, value: dict[str, Any]) -> None:
        """Check if a chain_start event indicates a resumed graph execution."""
        if value.get("name") != "LangGraph":
            return
        input_data = value.get("data", {}).get("input")
        if hasattr(input_data, "resume") and input_data.resume:
            self._is_resuming = True

    def _finish(self) -> list[str]:
        """
        Emit the finish + done sequence exactly once.

        Returns a list (not async generator) so callers can use `yield from`.
        """
        if self._finished:
            return [SSE_DONE]

        self._finished = True
        events = []

        if not self._approval_pending:
            # Close any open content streams synchronously by draining the async generator.
            # In practice, close_all() only yields pre-built strings, so we build them directly.
            if self._content.has_open_stream:
                # We can't use async iteration in a sync method, so we emit the close events
                # based on known state.
                if self._content._reasoning_open:
                    events.append(format_sse_event(
                        "reasoning-end", id=self._content.reasoning_id))
                    self._content._reasoning_open = False
                if self._content._text_open:
                    events.append(format_sse_event(
                        "text-end", id=self._content.text_id))
                    self._content._text_open = False

            events.append(format_sse_event("finish"))

        events.append(SSE_DONE)
        return events
