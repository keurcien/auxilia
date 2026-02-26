

"""
Adapter for converting LangGraph/LangChain event streams to the AI SDK v5 streaming protocol.

This is the main entry point. It routes incoming LangGraph events to focused handlers
and manages the overall stream lifecycle (start → content/tools → finish).

Usage:
    adapter = AISDKStreamAdapter()
    async for sse_event in adapter.stream(langgraph_event_stream):
        yield sse_event
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from .content_stream import ContentStreamManager
from .handlers import (
    _extract_tool_output,
    _register_model_tool_signatures,
    handle_chat_model_end,
    handle_chat_model_stream,
    handle_interrupt,
    handle_tool_end,
    handle_tool_start,
)
from .sse import SSE_DONE, format_sse_event
from .tool_tracker import ToolCallTracker, make_tool_signature, normalize_tool_call

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
        tool_ui_metadata: dict[str, dict[str, str]] | None = None,
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
        self._tool_ui_metadata = tool_ui_metadata or {}

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
            async for event in handle_chat_model_stream(
                chunk,
                self._content,
                self._tools,
                self._tool_ui_metadata,
            ):
                yield event

        elif event_type == "on_chat_model_end":
            async for event in handle_chat_model_end(
                value,
                self._tools,
                self._tool_ui_metadata,
            ):
                yield event

        elif event_type == "on_tool_start":
            async for event in handle_tool_start(
                value,
                self._content,
                self._tools,
                self._tool_ui_metadata,
            ):
                yield event

        elif event_type == "on_tool_end":
            async for event in handle_tool_end(value, self._tools):
                yield event

        elif event_type == "on_chain_start":
            self._detect_resume(value)

        elif event_type == "on_chain_stream":
            has_approvals = False
            async for event in handle_interrupt(
                value,
                self._tools,
                self._tool_ui_metadata,
            ):
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


class SlackStreamAdapter:
    """
    Adapts LangGraph event streams to typed event dicts for Slack.

    Yields structured dicts instead of SSE strings:
    - {"type": "text", "content": "..."}
    - {"type": "tool_start", "tool_call_id": "...", "tool_name": "..."}
    - {"type": "tool_end", "tool_call_id": "...", "tool_name": "...", "input": {...}, "output": ...}
    - {"type": "tool_approval_request", "tool_call_id": "...", "tool_name": "...", "input": {...}}
    """

    def __init__(self):
        self._content = ContentStreamManager()
        self._tools = ToolCallTracker()
        self._approval_pending = False

    async def stream(self, events: AsyncGenerator[Any, None]) -> AsyncGenerator[dict[str, Any], None]:
        try:
            async for value in events:
                if not isinstance(value, dict) or "event" not in value:
                    continue
                async for event in self._route_event(value):
                    yield event
        except Exception as e:
            body = getattr(e, "body", None)
            msg = (body.get("message") if isinstance(body, dict) else None) or str(e)
            yield {"type": "error", "content": msg}

    async def _route_event(self, value: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        event_type = value["event"]

        if event_type == "error":
            error_data = value.get("data", {}).get("error", "Unknown error")
            if isinstance(error_data, dict):
                msg = error_data.get("message") or str(error_data)
            else:
                msg = str(error_data)
            yield {"type": "error", "content": msg}

        elif event_type == "on_chat_model_stream":
            chunk = value.get("data", {}).get("chunk")
            if not chunk:
                return

            # Accumulate tool call args silently
            tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
            if tool_call_chunks:
                for raw_chunk in tool_call_chunks:
                    tc = normalize_tool_call(raw_chunk)
                    tool_call_id = tc["id"]
                    tool_name = tc["name"]
                    args_delta = tc.get("args", "") or ""
                    index = tc.get("index", 0)

                    if tool_call_id and tool_name:
                        self._tools.start_call(
                            tool_call_id, tool_name,
                            args_buffer=args_delta,
                            index=index,
                        )
                    elif args_delta:
                        match = self._tools.find_active_by_index(index) or self._tools.find_sole_active()
                        if match:
                            _, tracked = match
                            tracked.args_buffer += args_delta

            # Yield text content
            raw_content = getattr(chunk, "content", None)
            if raw_content and isinstance(raw_content, str):
                yield {"type": "text", "content": raw_content}
            elif raw_content and isinstance(raw_content, list):
                for part in raw_content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        yield {"type": "text", "content": part["text"]}
                    elif isinstance(part, str):
                        yield {"type": "text", "content": part}

        elif event_type == "on_chat_model_end":
            output = value.get("data", {}).get("output")
            if not output:
                return
            for raw_tc in getattr(output, "tool_calls", []):
                tc = normalize_tool_call(raw_tc)
                tool_call_id = tc["id"]
                tool_name = tc["name"]
                tool_args = tc["args"]
                if tool_call_id:
                    signature = make_tool_signature(tool_name, tool_args)
                    self._tools.register_signature(signature, tool_call_id)

        elif event_type == "on_tool_start":
            tool_name = value.get("name")
            raw_input = value.get("data", {}).get("input", {})
            runtime = raw_input.get("runtime")
            tool_call_id = getattr(runtime, "tool_call_id", None) if runtime else None
            if not tool_call_id:
                tool_call_id = value.get("run_id")
            yield {"type": "tool_start", "tool_call_id": tool_call_id, "tool_name": tool_name}

        elif event_type == "on_tool_end":
            tool_output = value.get("data", {}).get("output")
            if not tool_output:
                return
            tool_call_id = getattr(tool_output, "tool_call_id", None)
            if not tool_call_id:
                return

            # Get the tool name and accumulated input from the tracker
            tracked = self._tools.get_active(tool_call_id)
            tool_name = tracked.name if tracked else "unknown"
            tool_input = {}
            if tracked and tracked.args_buffer:
                try:
                    tool_input = json.loads(tracked.args_buffer)
                except (json.JSONDecodeError, TypeError):
                    tool_input = {"raw": tracked.args_buffer}

            output = _extract_tool_output(tool_output)
            self._tools.finish_call(tool_call_id)

            yield {
                "type": "tool_end",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "input": tool_input,
                "output": output,
            }

        elif event_type == "on_chain_stream":
            chunk = value.get("data", {}).get("chunk")
            if not chunk or not isinstance(chunk, dict):
                return

            node_name = value.get("name")
            if node_name == "model":
                _register_model_tool_signatures(chunk, self._tools)
                return

            interrupt_data = chunk.get("__interrupt__")
            if not interrupt_data or len(interrupt_data) == 0:
                return

            interrupt = interrupt_data[0]
            interrupt_value = getattr(interrupt, "value", None)
            if not interrupt_value or not isinstance(interrupt_value, dict):
                return

            action_requests = interrupt_value.get("action_requests", [])
            for action_request in action_requests:
                tool_name = action_request.get("name")
                tool_input = action_request.get("args", {})
                signature = make_tool_signature(tool_name, tool_input)
                tool_call_id = self._tools.resolve_id_for_signature(signature)

                self._approval_pending = True
                yield {
                    "type": "tool_approval_request",
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "input": tool_input,
                }
