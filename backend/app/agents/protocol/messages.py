"""LangChain message ⇄ JSON helpers shared by the protocol emitter, the
protocol endpoints (`/threads/{id}/state`) and the thread history endpoint.

`serialize_message` produces the dict shape the `@langchain/langgraph-sdk`
client coerces back into `BaseMessage`s (`type`, `content`, `id`, plus
`tool_calls` / `tool_call_id` / `status` / `artifact` when present).
"""

import dataclasses
import json
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage
from langgraph.types import Overwrite


def serialize_message(msg: Any) -> dict[str, Any]:
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
    if getattr(msg, "artifact", None) is not None:
        d["artifact"] = msg.artifact
    return d


# A tool result in a hydration snapshot is cut at this many characters. The
# whole result stays one request away (`GET /threads/{id}/messages/{id}`), so
# a thread's snapshot costs O(messages), not O(bytes the tools ever returned).
TOOL_PREVIEW_CHARS = 16_000

# The one artifact the client reads whole: an MCP-app tool's, whose
# `structuredContent` feeds the app iframe. Every other artifact is a copy of
# `content` (`structured_content`), i.e. dead weight on the wire.
_APP_ARTIFACT_KEY = "mcp_app_resource_uri"


def serialize_message_preview(
    msg: Any, *, limit: int = TOOL_PREVIEW_CHARS
) -> dict[str, Any]:
    """`serialize_message`, bounded for a thread snapshot.

    Tool messages only: `content` longer than `limit` characters is replaced
    by its first `limit` characters (as text), with the full length recorded in
    `additional_kwargs["truncated"]["chars"]` so the client can offer the rest;
    a non-app `artifact` is dropped. Every other message is serialized whole.
    """
    d = serialize_message(msg)
    if d.get("type") != "tool":
        return d
    artifact = d.get("artifact")
    if artifact is not None and (
        not isinstance(artifact, dict) or not artifact.get(_APP_ARTIFACT_KEY)
    ):
        del d["artifact"]
    text = text_of(d.get("content"))
    if len(text) > limit:
        d["content"] = text[:limit]
        kwargs = dict(d.get("additional_kwargs") or {})
        kwargs["truncated"] = {"chars": len(text)}
        d["additional_kwargs"] = kwargs
    return d


def json_default(obj: Any) -> Any:
    """`json.dumps(default=…)` for anything a LangGraph run can put in an
    event: messages, UUIDs, dataclasses (`Interrupt`), pydantic models, the
    deepagents `Overwrite` reducer wrapper. Falls back to `str()` rather than
    raising — a stray object must never take a live stream down."""
    if isinstance(obj, BaseMessage):
        return serialize_message(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Overwrite):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    return str(obj)


def text_of(content: Any) -> str:
    """Stringify a message `content` for a single text block: strings pass
    through, block lists concatenate their text parts, anything else is
    JSON-encoded so structured tool results stay readable."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(p, dict) and p.get("type") == "text" for p in content
    ):
        return "".join(p.get("text", "") for p in content)
    try:
        return json.dumps(content, default=json_default)
    except (TypeError, ValueError):
        return str(content)
