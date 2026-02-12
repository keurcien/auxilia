"""Adapter for converting LangChain/LangGraph events to AI SDK streaming protocol."""

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any


class StreamState:
    """Maintains state for an active streaming session."""

    def __init__(self):
        self.message_id = str(uuid.uuid4())
        self.text_id = str(uuid.uuid4())
        self.reasoning_id = str(uuid.uuid4())
        self.text_started = False
        self.reasoning_started = False
        # Track active tool calls: {tool_call_id: {"name": str, "args_buffer": str, "skip_events": bool}}
        self.active_tool_calls: dict[str, dict[str, Any]] = {}
        self.is_resuming = False
        self.approval_pending = False
        # Store pending tool calls from model node for HITL correlation
        self.pending_tool_calls: list[dict[str, Any]] = []


class SlackStreamAdapter:
    """Adapts LangChain event streams to Slack streaming protocol."""

    async def to_data_stream(self, stream: AsyncGenerator[Any, None]) -> AsyncGenerator[str, None]:
        """Convert LangChain event stream to Slack streaming protocol."""

        async for value in stream:
            if value["event"] == "on_chat_model_stream":
                chunk = value.get("data", {}).get("chunk")
                yield chunk.content


class AISDKStreamAdapter:
    """Adapts LangChain event streams to AI SDK v5 streaming protocol."""

    def __init__(
        self,
        message_id: str | None = None,
        is_resume: bool = False,
        rejected_tool_calls: list[dict] | None = None,
        approved_tool_call_ids: list[str] | None = None,
    ):
        self.state = StreamState()

        # Allow reusing a message ID (e.g., when resuming after HITL approval)
        if message_id:
            self.state.message_id = message_id

        # Mark if this is a resume stream (to skip emitting start event)
        self.state.is_resuming = is_resume

        # Store rejected tool calls to emit error events at stream start
        self.rejected_tool_calls = rejected_tool_calls or []

        # Store approved tool call IDs to skip their input events (already shown in UI)
        self.approved_tool_call_ids = set(approved_tool_call_ids or [])

        # Also add rejected tool call IDs to skip their input events
        self.approved_tool_call_ids.update(
            r["toolCallId"] for r in self.rejected_tool_calls
        )

    @staticmethod
    def _emit_event(event_type: str, **data) -> str:
        """Format an event as Server-Sent Events (SSE)."""
        event_data = {"type": event_type, **data}
        return f"data: {json.dumps(event_data)}\n\n"

    # -------------------------------------------------------------------------
    # Text and Reasoning Content Handlers
    # -------------------------------------------------------------------------

    async def _handle_text_content(self, text: str) -> AsyncGenerator[str, None]:
        """Handle text content streaming."""
        if not text:
            return

        # End reasoning if we're switching to text
        if self.state.reasoning_started:
            yield self._emit_event("reasoning-end", id=self.state.reasoning_id)
            self.state.reasoning_started = False

        # Start text block if needed
        if not self.state.text_started:
            yield self._emit_event("text-start", id=self.state.text_id)
            self.state.text_started = True

        yield self._emit_event("text-delta", id=self.state.text_id, delta=text)

    async def _handle_reasoning_content(
        self, thinking: str
    ) -> AsyncGenerator[str, None]:
        """Handle reasoning/thinking content streaming."""
        if not thinking:
            return

        # End text if we're switching to reasoning
        if self.state.text_started:
            yield self._emit_event("text-end", id=self.state.text_id)
            self.state.text_started = False

        # Start reasoning block if needed
        if not self.state.reasoning_started:
            yield self._emit_event("reasoning-start", id=self.state.reasoning_id)
            self.state.reasoning_started = True

        yield self._emit_event(
            "reasoning-delta", id=self.state.reasoning_id, delta=thinking
        )

    async def _handle_content_array(
        self, content_list: list
    ) -> AsyncGenerator[str, None]:
        """Handle array-based content (e.g., Anthropic format)."""
        for content_item in content_list:
            if not isinstance(content_item, dict):
                continue

            content_type = content_item.get("type")

            if content_type == "text":
                text = content_item.get("text", "")
                if text:
                    async for event in self._handle_text_content(text):
                        yield event

            elif content_type == "thinking":
                thinking = content_item.get("thinking", "")
                if thinking:
                    async for event in self._handle_reasoning_content(thinking):
                        yield event

    async def _end_active_streams(self) -> AsyncGenerator[str, None]:
        """End any currently active text or reasoning streams."""
        if self.state.reasoning_started:
            yield self._emit_event("reasoning-end", id=self.state.reasoning_id)
            self.state.reasoning_started = False

        if self.state.text_started:
            yield self._emit_event("text-end", id=self.state.text_id)
            self.state.text_started = False

    # -------------------------------------------------------------------------
    # Tool Call Streaming Handlers
    # -------------------------------------------------------------------------

    async def _handle_tool_call_chunks(
        self, tool_call_chunks: list
    ) -> AsyncGenerator[str, None]:
        """Handle streaming tool call chunks from the model."""
        for chunk in tool_call_chunks:
            # Normalize chunk to dict format
            if not isinstance(chunk, dict):
                chunk = {
                    "id": getattr(chunk, "id", None),
                    "name": getattr(chunk, "name", None),
                    "args": getattr(chunk, "args", ""),
                    "index": getattr(chunk, "index", 0),
                }

            tool_call_id = chunk.get("id")
            tool_name = chunk.get("name")
            args_delta = chunk.get("args", "") or ""
            index = chunk.get("index", 0)

            # First chunk for this tool call - has the id and name
            if tool_call_id and tool_name:
                # End any active text/reasoning streams before tool call
                async for event in self._end_active_streams():
                    yield event

                # Check if this was already approved/rejected (HITL resume)
                skip_events = tool_call_id in self.approved_tool_call_ids

                self.state.active_tool_calls[tool_call_id] = {
                    "name": tool_name,
                    "args_buffer": args_delta,
                    "skip_events": skip_events,
                    "index": index,
                }

                if skip_events:
                    continue

                yield self._emit_event(
                    "tool-input-start",
                    toolCallId=tool_call_id,
                    toolName=tool_name,
                )

                # Emit initial delta if args came with the first chunk
                if args_delta:
                    yield self._emit_event(
                        "tool-input-delta",
                        toolCallId=tool_call_id,
                        inputTextDelta=args_delta,
                    )

            elif args_delta:
                # Subsequent chunks - find the matching tool call by index
                active_id = None
                active_call = None

                for tid, tdata in self.state.active_tool_calls.items():
                    if tdata.get("index") == index:
                        active_id = tid
                        active_call = tdata
                        break

                # Fallback: use the most recent tool call if only one is active
                if not active_call and len(self.state.active_tool_calls) == 1:
                    active_id = next(iter(self.state.active_tool_calls))
                    active_call = self.state.active_tool_calls[active_id]

                if active_call and active_id:
                    active_call["args_buffer"] += args_delta

                    if not active_call.get("skip_events"):
                        yield self._emit_event(
                            "tool-input-delta",
                            toolCallId=active_id,
                            inputTextDelta=args_delta,
                        )

    async def _finalize_streaming_tool_calls(
        self, tool_calls: list
    ) -> AsyncGenerator[str, None]:
        """Emit tool-input-available for completed streaming tool calls."""
        for tool_call in tool_calls:
            # Normalize to dict
            if not isinstance(tool_call, dict):
                tool_call = {
                    "id": getattr(tool_call, "id", None),
                    "name": getattr(tool_call, "name", None),
                    "args": getattr(tool_call, "args", {}),
                }

            tool_call_id = tool_call.get("id")
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})

            if not tool_call_id:
                continue

            # Check if we should skip (already approved/rejected)
            active = self.state.active_tool_calls.get(tool_call_id)
            if active and active.get("skip_events"):
                continue

            yield self._emit_event(
                "tool-input-available",
                toolCallId=tool_call_id,
                toolName=tool_name,
                input=tool_args,
            )

    # -------------------------------------------------------------------------
    # Event Type Handlers
    # -------------------------------------------------------------------------

    async def _handle_chat_model_stream(self, chunk: Any) -> AsyncGenerator[str, None]:
        """Handle on_chat_model_stream events."""
        if not chunk:
            return

        # Handle streaming tool calls (comes via tool_call_chunks)
        tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
        if tool_call_chunks:
            async for event in self._handle_tool_call_chunks(tool_call_chunks):
                yield event

        # Handle content (text, thinking, etc.)
        content = getattr(chunk, "content", None)
        if content:
            if isinstance(content, list):
                async for event in self._handle_content_array(content):
                    yield event
            elif isinstance(content, str):
                async for event in self._handle_text_content(content):
                    yield event

    async def _handle_chat_model_end(
        self, event: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle on_chat_model_end - finalize any streaming tool calls."""
        output = event.get("data", {}).get("output")
        if not output:
            return

        # Get tool_calls from the final AIMessage
        tool_calls = getattr(output, "tool_calls", [])
        if tool_calls:
            async for evt in self._finalize_streaming_tool_calls(tool_calls):
                yield evt

    async def _handle_tool_start(
        self, event: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle on_tool_start events (tool execution beginning)."""
        tool_name = event.get("name")
        raw_input = event.get("data", {}).get("input", {})
        runtime = raw_input.get("runtime")
        tool_call_id = getattr(runtime, "tool_call_id",
                               None) if runtime else None

        if not tool_call_id:
            tool_call_id = event.get("run_id")

        # Skip tool input events for tools that were already shown (approved/rejected)
        # but still track them for later output events
        if tool_call_id in self.approved_tool_call_ids:
            if tool_call_id and tool_name:
                self.state.active_tool_calls[tool_call_id] = {
                    "name": tool_name,
                    "args_buffer": "",
                    "skip_events": True,
                }
            return

        # Check if this tool call was already handled via streaming
        if tool_call_id in self.state.active_tool_calls:
            # Already emitted via streaming, skip
            return

        # End any active text/reasoning streams before showing tool
        async for stream_event in self._end_active_streams():
            yield stream_event

        tool_input = {
            k: v
            for k, v in raw_input.items()
            if k not in ("runtime", "context", "config", "stream_writer", "store")
        }

        if tool_call_id and tool_name:
            self.state.active_tool_calls[tool_call_id] = {
                "name": tool_name,
                "args_buffer": json.dumps(tool_input),
                "skip_events": False,
            }

            yield self._emit_event(
                "tool-input-start", toolCallId=tool_call_id, toolName=tool_name
            )
            yield self._emit_event(
                "tool-input-available",
                toolCallId=tool_call_id,
                toolName=tool_name,
                input=tool_input,
            )

    async def _handle_tool_end(
        self, event: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle on_tool_end events (tool execution complete)."""
        tool_output = event.get("data", {}).get("output")
        if not tool_output:
            return

        # Get tool_call_id from ToolMessage - this MUST match the original
        tool_call_id = getattr(tool_output, "tool_call_id", None)
        if not tool_call_id:
            return

        output = tool_output.content if hasattr(
            tool_output, "content") else tool_output

        # Handle list output (e.g., from some tools)
        if isinstance(output, list) and len(output) > 0:
            output = output[0]

        # Try to parse JSON from text output
        if isinstance(output, dict) and "text" in output:
            try:
                output = json.loads(output.get("text"))
            except (json.JSONDecodeError, TypeError):
                output = output.get("text") if isinstance(
                    output, dict) else output

        # Emit tool output event
        yield self._emit_event(
            "tool-output-available", toolCallId=tool_call_id, output=output
        )

        # Clean up tracking
        self.state.active_tool_calls.pop(tool_call_id, None)

    async def _handle_chain_stream(
        self, event: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle on_chain_stream events, including HITL interrupts."""
        chunk = event.get("data", {}).get("chunk")
        if not chunk or not isinstance(chunk, dict):
            return

        node_name = event.get("name")

        # Capture tool_calls from model node's AIMessage for later HITL correlation
        if node_name == "model":
            messages = chunk.get("messages", [])
            if messages:
                last_msg = messages[-1] if isinstance(
                    messages, list) else messages
                tool_calls = getattr(last_msg, "tool_calls", [])
                if tool_calls:
                    self.state.pending_tool_calls = tool_calls
            return

        # Check for interrupt message (HITL pending approval)
        interrupt_data = chunk.get("__interrupt__")
        if not interrupt_data:
            return

        # interrupt_data is a tuple of Interrupt objects
        if len(interrupt_data) == 0:
            return

        interrupt = interrupt_data[0]
        interrupt_value = getattr(interrupt, "value", None)
        if not interrupt_value or not isinstance(interrupt_value, dict):
            return

        action_requests = interrupt_value.get("action_requests", [])
        if not action_requests:
            return

        # Build a lookup from (name, args) to tool_call_id using stored pending_tool_calls
        tool_call_lookup: dict[tuple[str, str], str] = {}
        for tc in self.state.pending_tool_calls:
            key = (tc.get("name"), json.dumps(
                tc.get("args", {}), sort_keys=True))
            tool_call_lookup[key] = tc.get("id")

        # Emit tool input and approval events for each pending tool call
        has_new_approvals = False

        for action_request in action_requests:
            tool_name = action_request.get("name")
            tool_input = action_request.get("args", {})

            # Try to find the matching tool_call_id from the stored pending tool calls
            lookup_key = (tool_name, json.dumps(tool_input, sort_keys=True))
            tool_call_id = tool_call_lookup.get(lookup_key)

            # Fallback to generated UUID if not found
            if not tool_call_id:
                tool_call_id = str(uuid.uuid4())

            # Skip tools that were already shown (approved/rejected in this session)
            if tool_call_id in self.approved_tool_call_ids:
                continue

            has_new_approvals = True

            yield self._emit_event(
                "tool-input-start",
                toolCallId=tool_call_id,
                toolName=tool_name,
            )
            yield self._emit_event(
                "tool-input-available",
                toolCallId=tool_call_id,
                toolName=tool_name,
                input=tool_input,
            )
            yield self._emit_event(
                "tool-approval-request",
                approvalId=str(uuid.uuid4()),
                toolCallId=tool_call_id,
            )

        # Mark that we're waiting for approval
        if has_new_approvals:
            self.state.approval_pending = True

    async def _handle_error(self, event: dict[str, Any]) -> AsyncGenerator[str, None]:
        """Handle error events."""
        error_message = event.get("data", {}).get("error", "Unknown error")
        yield self._emit_event("error", errorText=error_message)
        yield self._emit_event("finish")
        yield "data: [DONE]\n\n"

    # -------------------------------------------------------------------------
    # Main Stream Conversion
    # -------------------------------------------------------------------------

    async def to_data_stream(
        self, stream: AsyncGenerator[Any, None]
    ) -> AsyncGenerator[str, None]:
        """
        Convert LangChain event stream to AI SDK v5 protocol.

        Args:
            stream: AsyncGenerator yielding LangChain events

        Yields:
            SSE-formatted strings for AI SDK protocol
        """
        # Emit start event with message ID
        yield self._emit_event("start", messageId=self.state.message_id)

        # Emit error events for rejected tool calls to update their state
        for rejected in self.rejected_tool_calls:
            yield self._emit_event(
                "tool-output-error",
                toolCallId=rejected["toolCallId"],
                errorText=rejected.get(
                    "reason", "Tool execution was rejected by user"),
            )

        try:
            async for value in stream:
                if not isinstance(value, dict) or "event" not in value:
                    continue

                event_type = value["event"]

                if event_type == "error":
                    async for event in self._handle_error(value):
                        yield event
                    return

                elif event_type == "on_chat_model_stream":
                    chunk = value.get("data", {}).get("chunk")
                    async for event in self._handle_chat_model_stream(chunk):
                        yield event

                elif event_type == "on_chat_model_end":
                    async for event in self._handle_chat_model_end(value):
                        yield event

                elif event_type == "on_tool_start":
                    async for event in self._handle_tool_start(value):
                        yield event

                elif event_type == "on_tool_end":
                    async for event in self._handle_tool_end(value):
                        yield event

                elif event_type == "on_chain_start":
                    node_name = value.get("name")
                    input_data = value.get("data", {}).get("input")

                    # Detect resume command at the start of the request
                    if node_name == "LangGraph":
                        if hasattr(input_data, "resume") and input_data.resume:
                            self.state.is_resuming = True

                elif event_type == "on_chain_stream":
                    async for event in self._handle_chain_stream(value):
                        yield event

                elif event_type == "on_chain_end":
                    pass

        except Exception as e:
            yield self._emit_event(
                "error", errorText=f"Stream processing error: {str(e)}"
            )
            yield self._emit_event("finish")
            yield "data: [DONE]\n\n"

        finally:
            # When HITL approval is pending:
            # - Don't emit text-end (keeps text block "open" in UI)
            # - Don't emit finish (message is not complete yet)
            # - Still emit [DONE] to close the HTTP/SSE connection
            if not self.state.approval_pending:
                async for event in self._end_active_streams():
                    yield event
                yield self._emit_event("finish")

            yield "data: [DONE]\n\n"
