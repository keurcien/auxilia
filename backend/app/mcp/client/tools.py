"""Per-tool policy for MCP results, at the seam where they become ToolMessages.

``langchain.mcp`` wraps every MCP tool with
``response_format="content_and_artifact"``: the text/image blocks become the
model-visible ``content`` and the server's ``structuredContent`` becomes
``ToolMessage.artifact`` — whole, uncapped. The model never sees the artifact,
but the checkpointer, the run event log, Langfuse and the thread snapshot all
serialise it, and nothing that manages context size (deepagents' eviction,
summarisation) looks at it, because it costs no tokens. A Google Drive
``download_file_content`` puts the file's base64 there: 8 MB per call that rode
along in every checkpoint of the thread — 96% of one production thread's state.

Two policies, chosen per tool when the toolset is built:

- **MCP-app tools** (a ``resourceUri`` on the tool definition): the widget
  iframe consumes ``structuredContent``, so the artifact is kept whole and
  stamped with the app resource URI and server id — how the client recognises
  an app result on hydration, since LangGraph persists the ToolMessage as is.
- **Every other tool**: ``structured_content`` is dropped. No client code reads
  it and the model never had it.
"""

import base64
import binascii
import re
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.messages.content import (
    ImageContentBlock,
    TextContentBlock,
    create_image_block,
    create_text_block,
)
from langchain_core.tools import BaseTool


_STRUCTURED_CONTENT_KEYS = ("structured_content", "structuredContent")
_GENERIC_BINARY_MIME_TYPES = frozenset(
    {"", "application/octet-stream", "binary/octet-stream"}
)
_MAX_INLINE_TEXT_BYTES = 200_000

# Anthropic's constraint on input_schema property keys; OpenAPI-generated
# servers (Twilio's `StartTime<`, Stripe-style `created[gte]`) break it.
_VALID_PROPERTY_KEY = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_INVALID_PROPERTY_KEY_CHARS = re.compile(r"[^a-zA-Z0-9_.-]+")
_MAX_PROPERTY_KEY_LENGTH = 64
# Longest first, so `<=` is not read as `<` followed by `=`.
_PROPERTY_KEY_OPERATORS = (
    ("<=", "_lte"),
    (">=", "_gte"),
    ("!=", "_ne"),
    ("<", "_lt"),
    (">", "_gt"),
    ("=", "_eq"),
)
# Keywords whose values are data, not subschemas.
_SCHEMA_DATA_KEYWORDS = frozenset({"const", "default", "enum", "examples"})


def normalize_mcp_tool_schema(tool: BaseTool) -> tuple[bool, tuple[str, ...]]:
    """Repair provider-breaking constructs in an MCP tool schema.

    Some servers convert Zod schemas to draft 2019/2020 while still emitting
    the draft-04 representation ``minimum: N, exclusiveMinimum: true``.
    OpenAI validates the declared modern draft and rejects the entire toolset
    because modern ``exclusiveMinimum`` / ``exclusiveMaximum`` must themselves
    be numbers. Preserve the bound's exact semantics recursively.

    Other servers emit local ``$ref`` pointers whose target is missing. Every
    supported provider asks LangChain to dereference the whole schema before a
    model call, so one dangling pointer otherwise prevents *all* tools from
    reaching the model. Drop only the invalid pointer; the MCP server remains
    the authority that validates the eventual tool arguments.
    """
    schema = getattr(tool, "args_schema", None)
    if not isinstance(schema, dict):
        return False, ()

    bounds_changed = False
    dangling_refs: set[str] = set()

    def is_number(value: Any) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool)

    def resolves(ref: str) -> bool:
        if ref == "#":
            return True
        if not ref.startswith("#/"):
            return False
        current: Any = schema
        for raw_component in ref[2:].split("/"):
            component = raw_component.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and component in current:
                current = current[component]
            elif isinstance(current, list) and component.isdigit():
                index = int(component)
                if index >= len(current):
                    return False
                current = current[index]
            else:
                return False
        return True

    def visit(value: Any) -> None:
        nonlocal bounds_changed
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        ref = value.get("$ref")
        if isinstance(ref, str) and not resolves(ref):
            value.pop("$ref")
            dangling_refs.add(ref)

        for exclusive_key, inclusive_key in (
            ("exclusiveMinimum", "minimum"),
            ("exclusiveMaximum", "maximum"),
        ):
            exclusive = value.get(exclusive_key)
            if not isinstance(exclusive, bool):
                continue
            inclusive = value.get(inclusive_key)
            if exclusive and is_number(inclusive):
                value[exclusive_key] = inclusive
                del value[inclusive_key]
            else:
                del value[exclusive_key]
            bounds_changed = True

        for child in value.values():
            visit(child)

    visit(schema)
    return bounds_changed, tuple(sorted(dangling_refs))


def _property_key_candidate(key: str) -> str:
    for operator, word in _PROPERTY_KEY_OPERATORS:
        key = key.replace(operator, word)
    key = _INVALID_PROPERTY_KEY_CHARS.sub("_", key).strip("_")
    return key[:_MAX_PROPERTY_KEY_LENGTH].rstrip("_") or "param"


def sanitize_mcp_property_keys(tool: BaseTool) -> tuple[str, ...]:
    """Rename schema property keys that providers reject, and map the model's
    arguments back to the server's names on every call.

    Anthropic rejects the *whole request* when one property key falls outside
    ``^[a-zA-Z0-9_.-]{1,64}$``, so a single tool would take every tool of the
    agent down with it. Renamed keys are unique across the whole schema, which
    lets the argument rewrite work by key alone at any depth. Returns the
    original keys that were renamed.
    """
    schema = getattr(tool, "args_schema", None)
    if not isinstance(schema, dict):
        return ()

    used: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key in _SCHEMA_DATA_KEYWORDS:
                    continue
                if key == "properties" and isinstance(child, dict):
                    used.update(child)
                    for subschema in child.values():
                        collect(subschema)
                else:
                    collect(child)

    collect(schema)

    originals: dict[str, str] = {}

    def renamed(key: str) -> str:
        candidate = _property_key_candidate(key)
        unique, suffix = candidate, 2
        while unique in used:
            tail = f"_{suffix}"
            unique = candidate[: _MAX_PROPERTY_KEY_LENGTH - len(tail)] + tail
            suffix += 1
        used.add(unique)
        originals[unique] = key
        return unique

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict) and any(
            not _VALID_PROPERTY_KEY.match(key) for key in properties
        ):
            mapping: dict[str, str] = {}
            rebuilt: dict[str, Any] = {}
            for key, subschema in properties.items():
                if _VALID_PROPERTY_KEY.match(key):
                    rebuilt[key] = subschema
                    continue
                new_key = mapping[key] = renamed(key)
                if isinstance(subschema, dict):
                    note = f"Original parameter name: {key}"
                    description = subschema.get("description")
                    subschema = {
                        **subschema,
                        "description": f"{description}\n\n{note}"
                        if isinstance(description, str) and description
                        else note,
                    }
                rebuilt[new_key] = subschema
            value["properties"] = rebuilt
            required = value.get("required")
            if isinstance(required, list):
                value["required"] = [mapping.get(key, key) for key in required]
        for key, child in value.items():
            if key in _SCHEMA_DATA_KEYWORDS:
                continue
            if key == "properties" and isinstance(child, dict):
                for subschema in child.values():
                    visit(subschema)
            else:
                visit(child)

    visit(schema)
    if not originals:
        return ()

    original_coroutine = getattr(tool, "coroutine", None)
    if original_coroutine is not None:

        def restore(value: Any) -> Any:
            if isinstance(value, dict):
                return {originals.get(k, k): restore(v) for k, v in value.items()}
            if isinstance(value, list):
                return [restore(item) for item in value]
            return value

        async def coroutine_with_original_keys(*args, **kwargs):
            return await original_coroutine(*args, **restore(kwargs))

        tool.coroutine = coroutine_with_original_keys
    return tuple(sorted(originals.values()))


def _text_from_generic_blob(data: bytes) -> str | None:
    """Decode a generic blob only when it is clearly textual."""
    if len(data) > _MAX_INLINE_TEXT_BYTES or b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    control_chars = sum(
        1 for char in text if ord(char) < 32 and char not in "\n\r\t\f\b"
    )
    if text and control_chars / len(text) > 0.01:
        return None
    return text


def _typed_generic_blob(
    block: dict[str, Any], data: bytes
) -> dict[str, Any] | ImageContentBlock | TextContentBlock | None:
    """Recover safe, model-supported types from an untyped MCP blob."""
    encoded = block.get("base64")
    if not isinstance(encoded, str):
        return None
    if data.startswith(b"%PDF-"):
        return {
            **block,
            "mime_type": "application/pdf",
            "filename": block.get("filename") or "attachment.pdf",
        }
    image_type: tuple[str, str] | None = None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        image_type = ("image/png", "png")
    elif data.startswith(b"\xff\xd8\xff"):
        image_type = ("image/jpeg", "jpg")
    elif data.startswith((b"GIF87a", b"GIF89a")):
        image_type = ("image/gif", "gif")
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        image_type = ("image/webp", "webp")
    if image_type is not None:
        mime_type, _ = image_type
        return create_image_block(base64=encoded, mime_type=mime_type)
    if (text := _text_from_generic_blob(data)) is not None:
        return create_text_block(text=text)
    return None


def normalize_mcp_tool_content(content: Any) -> Any:
    """Make untyped MCP file blocks safe to send to model providers.

    OpenAI rejects inline ``application/octet-stream`` files before the model
    can respond. Recover PDFs, common images and UTF-8 text by inspecting the
    payload; replace truly opaque binary data with a compact explanation.
    """
    if not isinstance(content, list):
        return content

    normalized: list[Any] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "file":
            normalized.append(block)
            continue
        mime_type = block.get("mime_type")
        normalized_mime = mime_type.lower() if isinstance(mime_type, str) else ""
        if normalized_mime not in _GENERIC_BINARY_MIME_TYPES:
            normalized.append(block)
            continue

        encoded = block.get("base64")
        replacement = None
        if isinstance(encoded, str):
            try:
                replacement = _typed_generic_blob(
                    block, base64.b64decode(encoded, validate=True)
                )
            except binascii.Error, ValueError:
                replacement = None
        if replacement is not None:
            normalized.append(replacement)
            continue

        source = block.get("url")
        source_note = f" Resource URL: {source}" if isinstance(source, str) else ""
        normalized.append(
            create_text_block(
                text=(
                    "The MCP tool returned an untyped binary attachment. Its bytes "
                    "were omitted because application/octet-stream cannot be sent "
                    f"to the model.{source_note}"
                )
            )
        )
    return normalized


def bound_tool_artifact(tool: BaseTool, ui_metadata: dict | None) -> None:
    """Wrap a tool's coroutine in place so every result's artifact follows the
    policy above: stamped and kept whole for an app tool (`ui_metadata` carries
    `mcp_app_resource_uri` + `mcp_server_id`), stripped of structured content
    for any other."""
    resource_uri = (ui_metadata or {}).get("mcp_app_resource_uri")
    server_id = (ui_metadata or {}).get("mcp_server_id")
    is_app_tool = bool(resource_uri and server_id)

    # Only a `StructuredTool` (what `langchain.mcp` builds) carries a coroutine
    # to wrap; anything else is left alone.
    original_coroutine = getattr(tool, "coroutine", None)
    if original_coroutine is None:
        return

    def rewrite(artifact):
        if is_app_tool:
            stamped = dict(artifact) if isinstance(artifact, dict) else {}
            stamped["mcp_app_resource_uri"] = resource_uri
            stamped["mcp_server_id"] = server_id
            return stamped
        if isinstance(artifact, dict):
            trimmed = {
                k: v for k, v in artifact.items() if k not in _STRUCTURED_CONTENT_KEYS
            }
            return trimmed or None
        return artifact

    async def bounded_coroutine(*args, **kwargs):
        result = await original_coroutine(*args, **kwargs)
        if isinstance(result, tuple) and len(result) == 2:
            content, artifact = result
            return normalize_mcp_tool_content(content), rewrite(artifact)
        if isinstance(result, ToolMessage):
            result.content = normalize_mcp_tool_content(result.content)
            result.artifact = rewrite(result.artifact)
        return result

    tool.coroutine = bounded_coroutine
