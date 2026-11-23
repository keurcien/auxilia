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

from app.memories.constants import MEMORY_TOOL_NAMES


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

# Keep MCP-app data and published-file descriptors, which the client reads.
# Other artifacts duplicate `content` (`structured_content`). File bytes are
# served separately and never belong in the transcript.
_APP_ARTIFACT_KEY = "mcp_app_resource_uri"


def serialize_message_preview(
    msg: Any, *, limit: int = TOOL_PREVIEW_CHARS
) -> dict[str, Any]:
    """`serialize_message`, bounded for a thread snapshot.

    Tool messages only: `content` longer than `limit` characters is replaced
    by its first `limit` characters (as text), with the full length recorded in
    `additional_kwargs["truncated"]["chars"]` so the client can offer the rest;
    unrelated `artifact` payloads are dropped. Every other message is serialized whole.
    """
    d = serialize_message(msg)
    if d.get("type") != "tool":
        return d
    artifact = d.get("artifact")
    if artifact is not None and (
        not isinstance(artifact, dict)
        or not (artifact.get(_APP_ARTIFACT_KEY) or artifact.get("auxilia_artifacts"))
    ):
        del d["artifact"]
    text = text_of(d.get("content"))
    if len(text) > limit:
        d["content"] = text[:limit]
        kwargs = dict(d.get("additional_kwargs") or {})
        kwargs["truncated"] = {"chars": len(text)}
        d["additional_kwargs"] = kwargs
    return d


def _public_content(message_type: str, content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    public: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            public.append({"type": "text", "text": block["text"]})
        elif message_type == "ai" and block_type in {"thinking", "reasoning"}:
            reasoning = block.get("thinking", block.get("reasoning"))
            if isinstance(reasoning, str) and reasoning:
                public.append({"type": "reasoning", "reasoning": reasoning})
        elif message_type == "human" and block_type == "image_url":
            image = block.get("image_url")
            url = image if isinstance(image, str) else None
            if isinstance(image, dict):
                url = image.get("url")
            if isinstance(url, str) and url:
                public.append({"type": "image_url", "image_url": {"url": url}})
        elif (
            message_type == "human"
            and block_type == "file"
            and isinstance(block.get("base64"), str)
        ):
            public.append(
                {
                    "type": "file",
                    "base64": block["base64"],
                    "filename": (
                        block["filename"]
                        if isinstance(block.get("filename"), str)
                        else "file"
                    ),
                    "mime_type": (
                        block["mime_type"]
                        if isinstance(block.get("mime_type"), str)
                        else "application/octet-stream"
                    ),
                }
            )
    return public


def serialize_public_message(msg: Any) -> dict[str, Any] | None:
    """Serialize only transcript fields safe for an unauthenticated snapshot."""
    message_type = getattr(msg, "type", "unknown")
    message_name = getattr(msg, "name", None)
    kwargs = getattr(msg, "additional_kwargs", {}) or {}
    response_metadata = getattr(msg, "response_metadata", {}) or {}
    if (
        message_type not in {"human", "ai", "tool"}
        or (message_type == "tool" and message_name in MEMORY_TOOL_NAMES)
        or response_metadata.get("structured_output")
        or (message_name == "host" and kwargs.get("host_notice"))
        or (
            message_type == "human"
            and text_of(getattr(msg, "content", ""))
            .lstrip()
            .startswith("[Host notice]")
        )
    ):
        return None

    serialized = serialize_message_preview(msg)
    content = _public_content(message_type, serialized["content"])
    raw_tool_calls = serialized.get("tool_calls")
    public_tool_calls = (
        [
            tool_call
            for tool_call in raw_tool_calls
            if not isinstance(tool_call, dict)
            or tool_call.get("name") not in MEMORY_TOOL_NAMES
        ]
        if isinstance(raw_tool_calls, list)
        else None
    )
    has_content = bool(content.strip()) if isinstance(content, str) else bool(content)
    if (
        message_type == "ai"
        and isinstance(raw_tool_calls, list)
        and raw_tool_calls
        and not public_tool_calls
        and not has_content
    ):
        return None
    public: dict[str, Any] = {
        "type": serialized["type"],
        "content": content,
        "id": serialized["id"],
    }
    if public_tool_calls:
        public["tool_calls"] = public_tool_calls
    for key in ("tool_call_id", "status", "name"):
        if key in serialized:
            public[key] = serialized[key]

    safe_kwargs: dict[str, Any] = {}
    attachments = kwargs.get("attachments")
    if message_type == "human" and isinstance(attachments, list):
        attachment_ids: list[str] = []
        for item in attachments:
            value = item if isinstance(item, str) else None
            if isinstance(item, dict):
                value = item.get("id")
            try:
                if isinstance(value, str):
                    attachment_ids.append(str(UUID(value)))
            except ValueError:
                continue
        if attachment_ids:
            safe_kwargs["attachments"] = attachment_ids
    display_text = kwargs.get("display_text")
    if message_type == "human" and isinstance(display_text, str):
        safe_kwargs["display_text"] = display_text
    inline_text_files = kwargs.get("inline_text_files")
    if message_type == "human" and isinstance(inline_text_files, list):
        safe_inline_files = []
        for item in inline_text_files:
            if not isinstance(item, dict):
                continue
            block_index = item.get("block_index")
            filename = item.get("filename")
            media_type = item.get("media_type")
            if (
                type(block_index) is int
                and block_index >= 0
                and isinstance(filename, str)
                and isinstance(media_type, str)
            ):
                safe_inline_files.append(
                    {
                        "block_index": block_index,
                        "filename": filename,
                        "media_type": media_type,
                    }
                )
        if safe_inline_files:
            safe_kwargs["inline_text_files"] = safe_inline_files
    reasoning = kwargs.get("reasoning_content")
    if message_type == "ai" and isinstance(reasoning, str):
        safe_kwargs["reasoning_content"] = reasoning
    truncated = kwargs.get("truncated")
    if message_type == "tool" and isinstance(truncated, dict):
        chars = truncated.get("chars")
        if type(chars) is int and chars >= 0:
            safe_kwargs["truncated"] = {"chars": chars}
    if safe_kwargs:
        public["additional_kwargs"] = safe_kwargs
    return public


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
    except TypeError, ValueError:
        return str(content)
