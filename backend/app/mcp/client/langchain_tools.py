"""Convert MCP tools into LangChain tools (MCP SDK v2).

This replaces ``langchain_mcp_adapters.tools.load_mcp_tools`` with the subset
auxilia actually uses, built on the MCP SDK v2 ``Client`` API. The output
shapes are kept byte-compatible with the adapter's:

* Each MCP tool becomes a ``StructuredTool`` with
  ``response_format="content_and_artifact"`` whose coroutine returns a
  ``(content_blocks, artifact)`` tuple — the shape
  ``inject_ui_metadata_into_tool`` (``app/mcp/client/tools.py``) wraps.
* ``structured_content`` is surfaced as ``{"structured_content": ...}`` in the
  artifact (MCP Apps stamp ``mcp_app_resource_uri`` into that dict).
* The tool's ``_meta`` lands in ``tool.metadata["_meta"]`` — read by
  ``_extract_mcp_app_resource_uri`` to detect UI-bearing tools.
* An MCP execution error (``CallToolResult.is_error``) raises a
  ``ToolException`` routed through ``handle_tool_error`` so the model sees a
  ``ToolMessage(status="error")`` and can self-correct; transport and
  conversion failures propagate and are caught by ``ToolErrorMiddleware``.

The ``client`` handed to :func:`load_mcp_tools` only needs ``list_tools`` and
``call_tool`` with the v2 ``Client`` signatures — in practice it is the
``ReconnectingSession`` proxy from ``app/agents/toolset.py``.
"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages.content import (
    create_file_block,
    create_image_block,
    create_text_block,
)
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp_types import (
    AudioContent,
    BlobResourceContents,
    CallToolResult,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    ListToolsResult,
    ResourceLink,
    TextContent,
    TextResourceContents,
    Tool as MCPTool,
)

from app.exceptions import DomainError


# Safety bound for tools/list pagination. A well-behaved server eventually
# returns a falsy next_cursor; this caps a misbehaving one that emits endless
# new cursors.
MAX_TOOL_LIST_PAGES = 1000


class MCPClientLike(Protocol):
    """The slice of the MCP v2 ``Client`` API this module consumes."""

    async def list_tools(self, *, cursor: str | None = None) -> ListToolsResult: ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult: ...


class MCPToolExecutionError(ToolException):
    """An MCP tool reported an execution error (``CallToolResult.is_error``).

    Carries the already-converted LangChain content blocks so the error can be
    surfaced to the model as a failed tool output instead of crashing the run.
    Deliberately narrow: transport/session failures and content-conversion
    errors are *not* ``ToolException`` subclasses, so they bypass
    ``handle_tool_error`` and propagate to ``ToolErrorMiddleware``.
    """

    def __init__(self, tool_content: list[dict]):
        super().__init__(_summarize_error(tool_content))
        self.tool_content = tool_content


def _summarize_error(tool_content: list[dict]) -> str:
    parts = [b["text"] for b in tool_content if b.get("type") == "text"]
    if parts:
        return "\n".join(parts)
    if tool_content:
        return (
            "MCP tool returned an error with no text content "
            f"({len(tool_content)} non-text content block(s))."
        )
    return "MCP tool returned an error with empty content."


def _handle_mcp_tool_error(error: ToolException) -> list[dict]:
    """``handle_tool_error`` callback: surface an MCP execution error as the
    failed ``ToolMessage``'s content. LangChain only routes ``ToolException``
    here, and this module only raises ``MCPToolExecutionError`` into that path;
    re-raise anything else defensively."""
    if isinstance(error, MCPToolExecutionError):
        if error.tool_content:
            return error.tool_content
        return [
            create_text_block(text="MCP tool returned an error with empty content.")
        ]
    raise error


def convert_mcp_content_block(content: ContentBlock) -> dict:
    """Convert one MCP content block to a LangChain content block dict."""
    if isinstance(content, TextContent):
        return create_text_block(text=content.text)

    if isinstance(content, ImageContent):
        return create_image_block(base64=content.data, mime_type=content.mime_type)

    if isinstance(content, AudioContent):
        raise NotImplementedError(
            "AudioContent conversion to LangChain content blocks is not "
            f"supported (mime type: {content.mime_type})."
        )

    if isinstance(content, ResourceLink):
        mime_type = content.mime_type or None
        if mime_type and mime_type.startswith("image/"):
            return create_image_block(url=str(content.uri), mime_type=mime_type)
        return create_file_block(url=str(content.uri), mime_type=mime_type)

    if isinstance(content, EmbeddedResource):
        resource = content.resource
        if isinstance(resource, TextResourceContents):
            return create_text_block(text=resource.text)
        if isinstance(resource, BlobResourceContents):
            mime_type = resource.mime_type or None
            if mime_type and mime_type.startswith("image/"):
                return create_image_block(base64=resource.blob, mime_type=mime_type)
            return create_file_block(base64=resource.blob, mime_type=mime_type)
        raise ValueError(f"Unknown embedded resource type: {type(resource).__name__}")

    raise ValueError(f"Unknown MCP content type: {type(content).__name__}")


def convert_call_tool_result(result: CallToolResult) -> tuple[list[dict], dict | None]:
    """Convert a ``CallToolResult`` to the ``(content, artifact)`` tuple a
    ``response_format="content_and_artifact"`` tool returns.

    Raises:
        MCPToolExecutionError: The tool reported ``is_error=True``.
    """
    tool_content = [convert_mcp_content_block(block) for block in result.content]

    if result.is_error:
        raise MCPToolExecutionError(tool_content)

    artifact: dict | None = None
    if result.structured_content is not None:
        artifact = {"structured_content": result.structured_content}

    return tool_content, artifact


def convert_mcp_tool_to_langchain_tool(
    client: MCPClientLike,
    tool: MCPTool,
    *,
    server_name: str | None = None,
    tool_name_prefix: bool = False,
) -> BaseTool:
    """Build a LangChain ``StructuredTool`` bound to ``client`` for one MCP tool."""

    async def call_tool(**arguments: Any) -> tuple[list[dict], dict | None]:
        result = await client.call_tool(tool.name, arguments)
        return convert_call_tool_result(result)

    annotations = tool.annotations.model_dump() if tool.annotations is not None else {}
    meta = {"_meta": tool.meta} if tool.meta is not None else {}
    metadata = {**annotations, **meta} or None

    lc_tool_name = tool.name
    if tool_name_prefix and server_name:
        lc_tool_name = f"{server_name}_{tool.name}"

    # handle_tool_error is typed to return str, but the callback returns
    # LangChain content blocks; langchain_core preserves list content onto the
    # ToolMessage unchanged. Same intentional mismatch as langchain-mcp-adapters.
    return StructuredTool(
        name=lc_tool_name,
        description=tool.description or "",
        args_schema=tool.input_schema,
        coroutine=call_tool,
        response_format="content_and_artifact",
        metadata=metadata,
        handle_tool_error=_handle_mcp_tool_error,  # type: ignore[arg-type]
    )


async def list_all_mcp_tools(client: MCPClientLike) -> list[MCPTool]:
    """Page through ``tools/list``, guarding against a server that never ends
    pagination: a repeated/cyclic ``next_cursor`` and a runaway page count both
    abort instead of spinning forever."""
    tools: list[MCPTool] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_TOOL_LIST_PAGES):
        response = await client.list_tools(cursor=cursor)
        tools.extend(response.tools)
        cursor = response.next_cursor
        if not cursor:
            return tools
        if cursor in seen_cursors:
            raise DomainError(
                "MCP server returned a repeated tools/list cursor; "
                "aborting to avoid an infinite pagination loop."
            )
        seen_cursors.add(cursor)
    raise DomainError(
        f"MCP server exceeded {MAX_TOOL_LIST_PAGES} tools/list pages; "
        "aborting to avoid an unbounded pagination loop."
    )


async def load_mcp_tools(
    client: MCPClientLike,
    *,
    server_name: str | None = None,
    tool_name_prefix: bool = False,
) -> list[BaseTool]:
    """List every tool on ``client`` and convert them to LangChain tools."""
    tools = await list_all_mcp_tools(client)
    return [
        convert_mcp_tool_to_langchain_tool(
            client, tool, server_name=server_name, tool_name_prefix=tool_name_prefix
        )
        for tool in tools
    ]
