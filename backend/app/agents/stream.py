"""Stream adapters for agent invocation output.

Converts LangGraph astream(stream_mode=["messages", "values"]) output to:
- LangGraph native SSE events (LangGraphStreamAdapter)
- Slack typed event dicts (SlackStreamAdapter)
"""

import dataclasses
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Overwrite


logger = logging.getLogger(__name__)


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

    def _serialize_messages_event(self, data: Any, namespace: tuple | None) -> str:
        chunk, metadata = data
        serialized_chunk = _serialize_lc_message(chunk)
        if namespace:
            metadata = {
                **(metadata or {}),
                "langgraph_checkpoint_ns": "|".join(namespace),
            }
        return _encode_lg_sse(
            self._event_name("messages", namespace),
            [serialized_chunk, metadata],
        )

    def _serialize_values_event(self, data: Any, namespace: tuple | None) -> str:
        serialized_state = _serialize_state(data)
        return _encode_lg_sse(self._event_name("values", namespace), serialized_state)

    def _serialize_updates_event(self, data: Any, namespace: tuple | None) -> str:
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
        return _encode_lg_sse(self._event_name("updates", namespace), serialized)

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

        except GraphRecursionError:
            # Let the caller (runtime) catch this and surface a synthetic AI
            # message; the checkpoint state is intact at this point so the
            # next turn can pick up where we left off.
            raise
        except Exception as e:
            logger.exception("Stream processing error")
            yield _encode_lg_sse("error", {"message": str(e), "status_code": 500})


def encode_synthetic_ai_message_sse(
    message: BaseMessage, state_values: dict[str, Any]
) -> list[str]:
    """SSE chunks that surface a synthetic AI message after the stream stopped.

    Used when the graph aborts mid-run (e.g. recursion limit) and the runtime
    persists a fallback assistant turn — these chunks make the JS SDK render
    it without a special-case code path.
    """
    serialized = _serialize_lc_message(message)
    return [
        _encode_lg_sse("messages", [serialized, {}]),
        _encode_lg_sse("updates", {"agent": {"messages": [serialized]}}),
        _encode_lg_sse("values", _serialize_state(state_values)),
    ]


def _decode_sse_blocks(sse: str) -> list[tuple[str, Any]]:
    """Parse one published SSE string into `(event, data)` pairs.

    Each chunk in the run event log is `event: <name>\\ndata: <json>\\n\\n`
    (one event per publish, but we split defensively). Data lines are joined
    and JSON-decoded; non-JSON data is returned as a raw string.
    """
    pairs: list[tuple[str, Any]] = []
    for block in sse.split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if not event:
            continue
        raw = "\n".join(data_lines)
        try:
            pairs.append((event, json.loads(raw)))
        except (json.JSONDecodeError, TypeError):
            pairs.append((event, raw))
    return pairs


def _chunk_text(content: Any) -> str:
    """Extract streamable text from an AI message chunk's `content`.

    Providers send either a plain string delta or a list of content blocks;
    only `text` blocks are surfaced (reasoning/other blocks are skipped)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class SlackStreamAdapter:
    """Adapts the run's LangGraph SSE event log to typed Slack event dicts.

    Reads the same byte-identical SSE the HTTP `/runs/stream` consumer relays
    (so the worker publishes one canonical format) and yields:
    - {"type": "text", "content": "..."}
    - {"type": "tool_start", "tool_call_id": "...", "tool_name": "..."}
    - {"type": "error", "content": "..."}
    - {"type": "end", "status": "success" | "interrupted" | ...}

    Only top-level (non-namespaced) `messages` events are surfaced — subagent
    tokens stream under a `messages|<ns>` event and are intentionally skipped.
    Approval requests are *not* derived here: when an `end` event reports
    `interrupted`, the consumer reads them from the checkpoint
    (`pending_approval_requests`), which carries the real tool-call ids.
    """

    def __init__(self):
        self._tools_started: set[str] = set()

    async def stream(
        self, sse_stream: AsyncIterator[str]
    ) -> AsyncGenerator[dict[str, Any], None]:
        async for sse in sse_stream:
            for event, data in _decode_sse_blocks(sse):
                for out in self._process(event, data):
                    yield out

    def _process(self, event: str, data: Any) -> list[dict[str, Any]]:
        if event == "messages":
            return self._process_message(data)
        if event == "error":
            message = data.get("message") if isinstance(data, dict) else str(data)
            return [{"type": "error", "content": message or "Unknown error"}]
        if event == "end":
            status = data.get("status") if isinstance(data, dict) else None
            return [{"type": "end", "status": status}]
        return []

    def _process_message(self, data: Any) -> list[dict[str, Any]]:
        """Turn a top-level `messages` event ([chunk, metadata]) into events."""
        if not isinstance(data, list) or not data:
            return []
        chunk = data[0]
        if not isinstance(chunk, dict):
            return []
        # `stream_mode="messages"` yields every node's messages, including the
        # `ToolMessage` from the tools node whose `content` is the raw tool-result
        # payload. Only AI output is user-facing text / tool calls — surfacing a
        # ToolMessage's content would dump the raw tool result into the chat.
        if chunk.get("type") not in ("AIMessageChunk", "ai", "AIMessage"):
            return []

        events: list[dict[str, Any]] = []
        for tc in chunk.get("tool_call_chunks") or chunk.get("tool_calls") or []:
            tc_id, name = tc.get("id"), tc.get("name")
            if tc_id and name and tc_id not in self._tools_started:
                self._tools_started.add(tc_id)
                events.append(
                    {"type": "tool_start", "tool_call_id": tc_id, "tool_name": name}
                )

        text = _chunk_text(chunk.get("content", ""))
        if text:
            events.append({"type": "text", "content": text})
        return events
