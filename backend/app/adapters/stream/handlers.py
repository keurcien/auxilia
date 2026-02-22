"""Handlers for individual LangGraph/LangChain event types."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from .content_stream import ContentStreamManager
from .sse import format_sse_event
from .tool_tracker import ToolCallTracker, make_tool_signature, normalize_tool_call

logger = logging.getLogger(__name__)

# Keys that are LangGraph internals and should not leak into tool input.
_INTERNAL_INPUT_KEYS = frozenset(
    {"runtime", "context", "config", "stream_writer", "store"})


def _strip_internal_keys(raw_input: dict) -> dict:
    return {k: v for k, v in raw_input.items() if k not in _INTERNAL_INPUT_KEYS}


def _get_provider_metadata_for_tool(
    tool_name: str,
    tool_ui_metadata: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]] | None:
    if not tool_ui_metadata:
        return None

    tool_metadata = tool_ui_metadata.get(tool_name)
    if not tool_metadata:
        return None

    resource_uri = tool_metadata.get("mcp_app_resource_uri")
    server_id = tool_metadata.get("mcp_server_id")
    if not resource_uri or not server_id:
        return None

    return {
        "auxilia": {
            "mcpAppResourceUri": resource_uri,
            "mcpServerId": server_id,
        }
    }


async def handle_chat_model_stream(
    chunk: Any,
    content: ContentStreamManager,
    tools: ToolCallTracker,
    tool_ui_metadata: dict[str, dict[str, str]] | None = None,
) -> AsyncGenerator[str, None]:
    """Process a streaming chunk from the chat model (text, reasoning, or tool deltas)."""
    if not chunk:
        return

    # --- Tool call chunks ---
    tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
    if tool_call_chunks:
        for raw_chunk in tool_call_chunks:
            tc = normalize_tool_call(raw_chunk)
            tool_call_id = tc["id"]
            tool_name = tc["name"]
            args_delta = tc.get("args", "") or ""
            index = tc.get("index", 0)

            # New tool call starting (has both ID and name)
            if tool_call_id and tool_name:
                async for event in content.close_all():
                    yield event

                already_approved = tools.is_pre_approved(tool_call_id)
                tools.start_call(
                    tool_call_id, tool_name,
                    args_buffer=args_delta,
                    already_approved=already_approved,
                    index=index,
                )

                if already_approved:
                    continue

                event_payload = {
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                }
                provider_metadata = _get_provider_metadata_for_tool(
                    tool_name, tool_ui_metadata)
                if provider_metadata:
                    event_payload["providerMetadata"] = provider_metadata

                yield format_sse_event("tool-input-start", **event_payload)
                if args_delta:
                    yield format_sse_event("tool-input-delta", toolCallId=tool_call_id, inputTextDelta=args_delta)

            # Continuation delta (args only, no ID)
            elif args_delta:
                match = tools.find_active_by_index(
                    index) or tools.find_sole_active()
                if match:
                    active_id, tracked = match
                    tracked.args_buffer += args_delta
                    if not tracked.already_approved:
                        yield format_sse_event("tool-input-delta", toolCallId=active_id, inputTextDelta=args_delta)

    # --- Text / reasoning content ---
    raw_content = getattr(chunk, "content", None)
    if raw_content:
        if isinstance(raw_content, list):
            async for event in content.emit_content_array(raw_content):
                yield event
        elif isinstance(raw_content, str):
            async for event in content.emit_text(raw_content):
                yield event


async def handle_chat_model_end(
    event: dict[str, Any],
    tools: ToolCallTracker,
    tool_ui_metadata: dict[str, dict[str, str]] | None = None,
) -> AsyncGenerator[str, None]:
    """Finalize tool calls when the model finishes generating."""
    output = event.get("data", {}).get("output")
    if not output:
        return

    for raw_tc in getattr(output, "tool_calls", []):
        tc = normalize_tool_call(raw_tc)
        tool_call_id = tc["id"]
        tool_name = tc["name"]
        tool_args = tc["args"]

        if not tool_call_id:
            continue

        signature = make_tool_signature(tool_name, tool_args)
        tools.register_signature(signature, tool_call_id)

        tracked = tools.get_active(tool_call_id)
        if tracked and tracked.already_approved:
            continue

        event_payload = {
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "input": tool_args,
        }
        provider_metadata = _get_provider_metadata_for_tool(
            tool_name, tool_ui_metadata)
        if provider_metadata:
            event_payload["providerMetadata"] = provider_metadata

        yield format_sse_event("tool-input-available", **event_payload)


async def handle_tool_start(
    event: dict[str, Any],
    content: ContentStreamManager,
    tools: ToolCallTracker,
    tool_ui_metadata: dict[str, dict[str, str]] | None = None,
) -> AsyncGenerator[str, None]:
    """Handle a LangGraph tool node beginning execution."""
    tool_name = event.get("name")
    raw_input = event.get("data", {}).get("input", {})

    # Extract tool_call_id from runtime metadata, falling back to run_id
    runtime = raw_input.get("runtime")
    tool_call_id = getattr(runtime, "tool_call_id", None) if runtime else None
    if not tool_call_id:
        tool_call_id = event.get("run_id")

    tool_input = _strip_internal_keys(raw_input)
    signature = make_tool_signature(tool_name, tool_input)

    # Dedup: skip if we already emitted this exact tool call
    if tools.should_skip_emission(tool_call_id, signature):
        tools.register_signature(signature, tool_call_id)
        return

    # Pre-approved tools: track but don't emit UI events
    if tools.is_pre_approved(tool_call_id):
        tools.start_call(tool_call_id, tool_name, already_approved=True)
        return

    async for event_str in content.close_all():
        yield event_str

    tools.register_signature(signature, tool_call_id)
    tools.start_call(tool_call_id, tool_name,
                     args_buffer=json.dumps(tool_input))

    provider_metadata = _get_provider_metadata_for_tool(
        tool_name, tool_ui_metadata)

    start_payload = {
        "toolCallId": tool_call_id,
        "toolName": tool_name,
    }
    if provider_metadata:
        start_payload["providerMetadata"] = provider_metadata

    available_payload = {
        "toolCallId": tool_call_id,
        "toolName": tool_name,
        "input": tool_input,
    }
    if provider_metadata:
        available_payload["providerMetadata"] = provider_metadata

    yield format_sse_event("tool-input-start", **start_payload)
    yield format_sse_event("tool-input-available", **available_payload)


async def handle_tool_end(
    event: dict[str, Any],
    tools: ToolCallTracker,
) -> AsyncGenerator[str, None]:
    """Handle a tool finishing execution and producing output."""
    tool_output = event.get("data", {}).get("output")
    if not tool_output:
        return

    tool_call_id = getattr(tool_output, "tool_call_id", None)
    if not tool_call_id:
        return

    output = _extract_tool_output(tool_output)

    yield format_sse_event("tool-output-available", toolCallId=tool_call_id, output=output)
    tools.finish_call(tool_call_id)


def _extract_tool_output(tool_output: Any) -> Any:
    """
    Extract the meaningful output from a LangChain ToolMessage.

    Handles content attributes, list-wrapped outputs, and text-keyed dicts.
    Note: for multi-part outputs (lists), only the first element is used.
    This matches the AI SDK protocol which expects a single output per tool call.
    """
    output = tool_output.content if hasattr(
        tool_output, "content") else tool_output

    if isinstance(output, list) and len(output) > 0:
        output = output[0]

    if isinstance(output, dict) and "text" in output:
        try:
            return json.loads(output["text"])
        except (json.JSONDecodeError, TypeError):
            return output.get("text", output)

    return output


async def handle_interrupt(
    event: dict[str, Any],
    tools: ToolCallTracker,
    tool_ui_metadata: dict[str, dict[str, str]] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Handle a LangGraph interrupt containing tool approval requests.

    Returns True via the generator's final state if approvals were emitted,
    signaling the caller that the stream is paused for human input.
    """
    chunk = event.get("data", {}).get("chunk")
    if not chunk or not isinstance(chunk, dict):
        return

    node_name = event.get("name")

    # When the model node emits, register its tool signatures for later correlation
    if node_name == "model":
        _register_model_tool_signatures(chunk, tools)
        return

    interrupt_data = chunk.get("__interrupt__")
    if not interrupt_data or len(interrupt_data) == 0:
        return

    interrupt = interrupt_data[0]
    interrupt_value = getattr(interrupt, "value", None)
    if not interrupt_value or not isinstance(interrupt_value, dict):
        return

    action_requests = interrupt_value.get("action_requests", [])
    if not action_requests:
        return

    for action_request in action_requests:
        tool_name = action_request.get("name")
        tool_input = action_request.get("args", {})
        signature = make_tool_signature(tool_name, tool_input)

        tool_call_id = tools.resolve_id_for_signature(signature)

        if tools.is_pre_approved(tool_call_id):
            continue

        # Only emit tool-input events if not already streamed
        if not tools.is_signature_emitted(signature) and not tools.is_active(tool_call_id):
            provider_metadata = _get_provider_metadata_for_tool(
                tool_name, tool_ui_metadata)

            start_payload = {
                "toolCallId": tool_call_id,
                "toolName": tool_name,
            }
            if provider_metadata:
                start_payload["providerMetadata"] = provider_metadata

            available_payload = {
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "input": tool_input,
            }
            if provider_metadata:
                available_payload["providerMetadata"] = provider_metadata

            yield format_sse_event("tool-input-start", **start_payload)
            yield format_sse_event("tool-input-available", **available_payload)
            tools.register_signature(signature, tool_call_id)

        yield format_sse_event(
            "tool-approval-request",
            approvalId=str(uuid.uuid4()),
            toolCallId=tool_call_id,
        )


def _register_model_tool_signatures(chunk: dict, tools: ToolCallTracker) -> None:
    """Pre-register tool signatures from a model node's output for interrupt correlation."""
    messages = chunk.get("messages", [])
    if not messages:
        return

    last_msg = messages[-1] if isinstance(messages, list) else messages
    for tc in getattr(last_msg, "tool_calls", []):
        signature = make_tool_signature(tc.get("name", ""), tc.get("args", {}))
        tools.register_signature(signature, tc.get("id"))
