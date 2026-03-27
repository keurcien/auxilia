"""Stream adapters for agent invocation output.

Converts LangGraph astream(stream_mode=["messages", "values"]) output to:
- LangGraph native SSE events (LangGraphStreamAdapter)
- AI SDK v5 SSE strings (AISDKStreamAdapter)
- Slack typed event dicts (SlackStreamAdapter)

The library handles core stream conversion (text, reasoning, tool events,
HITL interrupts). A thin wrapper adds auxilia-specific features:
messageId, providerMetadata, resume/HITL, output normalization.
"""

import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from langchain_ai_sdk_adapter import to_ui_message_stream
from langchain_core.messages import BaseMessage
from langgraph.types import Overwrite


logger = logging.getLogger(__name__)

SSE_DONE = "data: [DONE]\n\n"


def _encode_sse(chunk: dict[str, Any]) -> str:
    return f"data: {json.dumps(chunk)}\n\n"


def _make_tool_signature(name: str, args: Any) -> str:
    """Deterministic content signature for matching tool calls across resume."""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except (json.JSONDecodeError, TypeError):
            args = {"raw": args}
    return f"{name}:{json.dumps(args or {}, sort_keys=True)}"


def _get_provider_metadata(
    tool_name: str,
    tool_ui_metadata: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]] | None:
    if not tool_ui_metadata:
        return None
    meta = tool_ui_metadata.get(tool_name)
    if not meta:
        return None
    uri = meta.get("mcp_app_resource_uri")
    sid = meta.get("mcp_server_id")
    if not uri or not sid:
        return None
    return {"auxilia": {"mcpAppResourceUri": uri, "mcpServerId": sid}}


def _normalize_tool_output(output: Any) -> Any:
    """Normalize tool output to a clean JSON value or string.

    Handles two cases:
    1. Library-wrapped structured content: {"_text": raw, "structuredContent": {...}}
       → normalizes the _text value, preserves the wrapper.
    2. Raw MCP content parts: [{"type": "text", "text": "{...}"}]
       → extracts the actual value.
    """
    if isinstance(output, dict) and "structuredContent" in output:
        output["_text"] = _normalize_raw_tool_output(output.get("_text"))
        return output
    return _normalize_raw_tool_output(output)


def _normalize_raw_tool_output(output: Any) -> Any:
    """Normalize raw MCP tool content to a clean JSON value or string.

    MCP tools via langchain-mcp-adapters return content as a list of
    content parts like [{"type": "text", "text": "{...}"}]. This extracts
    the actual value.
    """
    if isinstance(output, list) and len(output) > 0:
        output = output[0]
    if isinstance(output, dict) and "text" in output:
        try:
            return json.loads(output["text"])
        except (json.JSONDecodeError, TypeError):
            return output.get("text", output)
    if isinstance(output, str):
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            pass
    return output


# Event types to filter out (library-specific, not in AI SDK v5 protocol)
_STRIP_EVENTS = frozenset({"start-step", "finish-step"})

# Tool events that can carry providerMetadata
_TOOL_META_EVENTS = frozenset({"tool-input-start", "tool-input-available"})


class AISDKStreamAdapter:
    """Converts a LangGraph stream to AI SDK v5 SSE.

    Uses langchain-ai-sdk-adapter for core conversion (text, reasoning, tool
    events, HITL interrupts, structured content), then wraps the output with
    auxilia-specific features (messageId, providerMetadata, resume/HITL logic).
    """

    def __init__(
        self,
        message_id: str | None = None,
        is_resume: bool = False,
        rejected_tool_calls: list[dict] | None = None,
        approved_tool_call_ids: list[str] | None = None,
        approved_tool_calls: list[dict] | None = None,
        tool_ui_metadata: dict[str, dict[str, str]] | None = None,
    ):
        self._message_id = message_id or str(uuid.uuid4())
        self._rejected_tool_calls = rejected_tool_calls or []

        # Pre-approved IDs: explicit approvals + rejections (both already handled)
        self._pre_approved_ids: set[str] = set(approved_tool_call_ids or [])
        self._pre_approved_ids.update(
            r["toolCallId"] for r in self._rejected_tool_calls
        )

        # Signature → original_tool_call_id for content-based matching on resume
        self._pre_approved_signatures: dict[str, str] = {}
        for call in approved_tool_calls or []:
            name = call.get("toolName") or ""
            args = call.get("input") or {}
            tc_id = call.get("toolCallId") or ""
            if name and tc_id:
                self._pre_approved_signatures[_make_tool_signature(name, args)] = tc_id

        self._tool_ui_metadata = tool_ui_metadata or {}
        self._approval_pending = False

    async def stream(
        self, langchain_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[str, None]:
        try:
            async for chunk in to_ui_message_stream(langchain_stream):
                for sse in self._process(chunk):
                    yield sse
        except Exception as e:
            logger.exception("Stream processing error")
            yield _encode_sse(
                {
                    "type": "error",
                    "errorText": f"Stream processing error: {str(e)}",
                }
            )

        for event in self._finish():
            yield event

    def _process(self, chunk: dict[str, Any]) -> list[str]:
        event_type = chunk.get("type")

        if event_type in _STRIP_EVENTS:
            return []

        if event_type == "start":
            chunk["messageId"] = self._message_id
            events = [_encode_sse(chunk)]
            # Replay rejection results at stream start
            for r in self._rejected_tool_calls:
                events.append(
                    _encode_sse(
                        {
                            "type": "tool-output-error",
                            "toolCallId": r["toolCallId"],
                            "errorText": r.get(
                                "reason",
                                "Tool execution was rejected by user",
                            ),
                        }
                    )
                )
            return events

        if event_type == "finish":
            return []  # handled by _finish()

        # ── Tool input events ──────────────────────────────────────────
        if event_type in (
            "tool-input-start",
            "tool-input-delta",
            "tool-input-available",
        ):
            tc_id = chunk.get("toolCallId")
            tool_name = chunk.get("toolName")

            # Suppress pre-approved tools (by ID)
            if tc_id in self._pre_approved_ids:
                return []

            # Suppress pre-approved tools (by content signature)
            if event_type == "tool-input-available" and tool_name:
                sig = _make_tool_signature(tool_name, chunk.get("input"))
                if sig in self._pre_approved_signatures:
                    self._pre_approved_ids.add(tc_id)
                    return []

            # Strip library-specific field
            chunk.pop("dynamic", None)

            # Inject providerMetadata
            if tool_name and event_type in _TOOL_META_EVENTS:
                pm = _get_provider_metadata(tool_name, self._tool_ui_metadata)
                if pm:
                    chunk["providerMetadata"] = pm

            return [_encode_sse(chunk)]

        # ── Tool output ────────────────────────────────────────────────
        if event_type == "tool-output-available":
            chunk["output"] = _normalize_tool_output(chunk.get("output"))
            return [_encode_sse(chunk)]

        if event_type == "tool-output-error":
            return [_encode_sse(chunk)]

        # ── Tool approval ──────────────────────────────────────────────
        if event_type == "tool-approval-request":
            tc_id = chunk.get("toolCallId")
            if tc_id in self._pre_approved_ids:
                return []
            self._approval_pending = True
            return [_encode_sse(chunk)]

        # ── Everything else (text-start, text-delta, text-end, etc.) ──
        return [_encode_sse(chunk)]

    def _finish(self) -> list[str]:
        events = []
        if not self._approval_pending:
            events.append(_encode_sse({"type": "finish"}))
        events.append(SSE_DONE)
        return events


# ---------------------------------------------------------------------------
# LangGraph native SSE protocol
# ---------------------------------------------------------------------------


def _encode_lg_sse(event: str, data: Any) -> str:
    """Encode a LangGraph SSE event with event: and data: lines."""
    return f"event: {event}\ndata: {json.dumps(data, default=_lg_json_default)}\n\n"


def _lg_json_default(obj: Any) -> Any:
    """JSON fallback for LangGraph SSE serialization."""
    from uuid import UUID

    if isinstance(obj, UUID):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, BaseMessage):
        return _serialize_lc_message(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _serialize_lc_message(msg: Any) -> dict[str, Any]:
    """Serialize a LangChain message or chunk to a dict for the JS SDK.

    The @langchain/langgraph-sdk JS SDK accepts dicts with:
    - type: "ai"|"human"|"tool"|"system" (also "AIMessageChunk" etc.)
    - content: str or list of content blocks
    - id: str (required!)
    - tool_calls, tool_call_id, status, etc. as applicable
    """
    d: dict[str, Any] = {
        "type": getattr(msg, "type", "unknown"),
        "content": getattr(msg, "content", ""),
        "id": getattr(msg, "id", None),
    }
    if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
        d["tool_call_chunks"] = list(msg.tool_call_chunks)
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        d["tool_calls"] = list(msg.tool_calls)
    if hasattr(msg, "invalid_tool_calls") and msg.invalid_tool_calls:
        d["invalid_tool_calls"] = list(msg.invalid_tool_calls)
    if hasattr(msg, "tool_call_id"):
        d["tool_call_id"] = msg.tool_call_id
    if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
        d["additional_kwargs"] = msg.additional_kwargs
    if hasattr(msg, "response_metadata") and msg.response_metadata:
        d["response_metadata"] = msg.response_metadata
    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
        d["usage_metadata"] = (
            msg.usage_metadata
            if isinstance(msg.usage_metadata, dict)
            else msg.usage_metadata.model_dump()
            if hasattr(msg.usage_metadata, "model_dump")
            else {}
        )
    if hasattr(msg, "name") and msg.name:
        d["name"] = msg.name
    if hasattr(msg, "status") and msg.status:
        d["status"] = msg.status
    if hasattr(msg, "artifact") and msg.artifact:
        d["artifact"] = msg.artifact
    return d


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Serialize a LangGraph state dict for the values SSE event."""
    result: dict[str, Any] = {}
    for key, value in state.items():
        # Unwrap Overwrite wrapper (used by deep agents)
        if isinstance(value, Overwrite):
            value = value.value
        if key == "messages" and isinstance(value, list):
            result[key] = [
                _serialize_lc_message(m) if isinstance(m, BaseMessage) else m
                for m in value
            ]
        elif key == "__interrupt__" and isinstance(value, list):
            result[key] = [
                dataclasses.asdict(i)
                if dataclasses.is_dataclass(i) and not isinstance(i, type)
                else i
                for i in value
            ]
        else:
            result[key] = value
    return result


class LangGraphStreamAdapter:
    """Converts raw LangGraph astream output to native LangGraph SSE events.

    Iterates (stream_mode, data) tuples from agent.astream() and emits
    standard SSE with event: <mode> and data: <json>.

    When subgraphs=True, events arrive as (namespace, mode, data) tuples.
    Namespace info is emitted as pipe-separated segments in the SSE event
    field (e.g. "values|tools:uuid") so the JS SDK can route subagent events.
    """

    def __init__(self, subgraphs: bool = False):
        self._subgraphs = subgraphs

    def _event_name(self, mode: str, namespace: tuple | None) -> str:
        """Build SSE event name with optional namespace segments."""
        if namespace:
            ns_str = "|".join(namespace)
            return f"{mode}|{ns_str}"
        return mode

    def _serialize_messages_event(
        self, data: Any, namespace: tuple | None
    ) -> str:
        chunk, metadata = data
        serialized_chunk = _serialize_lc_message(chunk)
        if namespace:
            metadata = {**(metadata or {}), "langgraph_checkpoint_ns": "|".join(namespace)}
        return _encode_lg_sse(
            self._event_name("messages", namespace),
            [serialized_chunk, metadata],
        )

    def _serialize_values_event(
        self, data: Any, namespace: tuple | None
    ) -> str:
        serialized_state = _serialize_state(data)
        return _encode_lg_sse(
            self._event_name("values", namespace), serialized_state
        )

    def _serialize_updates_event(
        self, data: Any, namespace: tuple | None
    ) -> str:
        serialized = {}
        for node_name, node_data in data.items():
            if isinstance(node_data, dict):
                unwrapped = {}
                for k, v in node_data.items():
                    # Unwrap Overwrite wrapper (used by deep agents)
                    if isinstance(v, Overwrite):
                        v = v.value
                    if k == "messages":
                        if not isinstance(v, list):
                            v = [v]
                        v = [
                            _serialize_lc_message(m)
                            if isinstance(m, BaseMessage)
                            else m
                            for m in v
                        ]
                    unwrapped[k] = v
                serialized[node_name] = unwrapped
            else:
                serialized[node_name] = node_data
        return _encode_lg_sse(
            self._event_name("updates", namespace), serialized
        )

    async def stream(
        self, langchain_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[str, None]:
        try:
            async for event in langchain_stream:
                if self._subgraphs:
                    # With subgraphs=True: (namespace_tuple, mode, data)
                    namespace, mode, data = event
                    namespace = namespace or None
                else:
                    # Without subgraphs: (mode, data)
                    mode, data = event[0], event[1]
                    namespace = None

                if mode == "messages":
                    yield self._serialize_messages_event(data, namespace)
                elif mode == "values":
                    yield self._serialize_values_event(data, namespace)
                elif mode == "updates":
                    yield self._serialize_updates_event(data, namespace)

        except Exception as e:
            logger.exception("Stream processing error")
            yield _encode_lg_sse("error", {"message": str(e), "status_code": 500})


class SlackStreamAdapter:
    """Converts a LangGraph stream to typed Slack event dicts.

    Yields structured dicts:
    - {"type": "text", "content": "..."}
    - {"type": "tool_start", "tool_call_id": "...", "tool_name": "..."}
    - {"type": "tool_end", "tool_call_id": "...", "tool_name": "...", "input": {...}, "output": ...}
    - {"type": "tool_approval_request", "tool_call_id": "...", "tool_name": "...", "input": {...}}
    """

    def __init__(self):
        self._tool_info: dict[str, dict[str, Any]] = {}

    async def stream(
        self, langchain_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        try:
            async for chunk in to_ui_message_stream(langchain_stream):
                for event in self._process(chunk):
                    yield event
        except Exception as e:
            body = getattr(e, "body", None)
            msg = (body.get("message") if isinstance(body, dict) else None) or str(e)
            yield {"type": "error", "content": msg}

    def _process(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = chunk.get("type")

        if event_type == "text-delta":
            delta = chunk.get("delta", "")
            if delta:
                return [{"type": "text", "content": delta}]
            return []

        if event_type == "tool-input-start":
            tc_id = chunk.get("toolCallId")
            tool_name = chunk.get("toolName")
            if tc_id and tool_name:
                self._tool_info[tc_id] = {
                    "name": tool_name,
                    "input": {},
                    "args_buffer": "",
                }
            return [
                {
                    "type": "tool_start",
                    "tool_call_id": tc_id,
                    "tool_name": tool_name,
                }
            ]

        if event_type == "tool-input-delta":
            tc_id = chunk.get("toolCallId")
            args_delta = chunk.get("inputTextDelta", "")
            if tc_id in self._tool_info and args_delta:
                self._tool_info[tc_id]["args_buffer"] += args_delta
            return []

        if event_type == "tool-input-available":
            tc_id = chunk.get("toolCallId")
            tool_input = chunk.get("input", {})
            if tc_id in self._tool_info:
                self._tool_info[tc_id]["input"] = tool_input
            return []

        if event_type == "tool-output-available":
            tc_id = chunk.get("toolCallId")
            output = _normalize_tool_output(chunk.get("output"))
            info = self._tool_info.get(tc_id, {})
            tool_name = info.get("name", "unknown")
            tool_input = info.get("input", {})

            if not tool_input and info.get("args_buffer"):
                try:
                    tool_input = json.loads(info["args_buffer"])
                except (json.JSONDecodeError, TypeError):
                    tool_input = {"raw": info["args_buffer"]}

            return [
                {
                    "type": "tool_end",
                    "tool_call_id": tc_id,
                    "tool_name": tool_name,
                    "input": tool_input,
                    "output": output,
                }
            ]

        if event_type == "tool-output-error":
            tc_id = chunk.get("toolCallId")
            info = self._tool_info.get(tc_id, {})
            return [
                {
                    "type": "tool_end",
                    "tool_call_id": tc_id,
                    "tool_name": info.get("name", "unknown"),
                    "input": info.get("input", {}),
                    "output": chunk.get("errorText", "Tool execution failed"),
                }
            ]

        if event_type == "tool-approval-request":
            tc_id = chunk.get("toolCallId")
            info = self._tool_info.get(tc_id, {})
            return [
                {
                    "type": "tool_approval_request",
                    "tool_call_id": tc_id,
                    "tool_name": info.get("name", "unknown"),
                    "input": info.get("input", {}),
                }
            ]

        if event_type == "error":
            return [
                {
                    "type": "error",
                    "content": chunk.get("errorText", "Unknown error"),
                }
            ]

        return []
