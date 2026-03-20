import json

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.stream import AISDKStreamAdapter, SlackStreamAdapter


def _parse_sse(sse_str: str) -> dict | None:
    """Parse an SSE data line into a dict, or None for [DONE]."""
    if sse_str.strip() == "data: [DONE]":
        return None
    prefix = "data: "
    assert sse_str.startswith(prefix)
    return json.loads(sse_str[len(prefix):])


# ── Fixtures: LangGraph astream(stream_mode=["messages", "values"]) tuples ──


def _make_text_stream_events():
    """Simple text conversation: model streams 'Hello! How can I assist you today?'"""
    msg_id = "lc_run--019cd8c3-7104-7173-9361-b7f162dfa28c"

    # messages mode: streaming AIMessageChunks
    yield (
        "messages",
        (
            AIMessageChunk(content="", id=msg_id),
            {"langgraph_step": 1, "langgraph_node": "model"},
        ),
    )
    for word in ["Hello", "!", " How", " can", " I", " assist", " you", " today", "?"]:
        yield (
            "messages",
            (
                AIMessageChunk(content=word, id=msg_id),
                {"langgraph_step": 1, "langgraph_node": "model"},
            ),
        )

    # values mode: full state snapshot
    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="hi", id="user-msg-1"),
                AIMessage(
                    content="Hello! How can I assist you today?",
                    id=msg_id,
                ),
            ]
        },
    )


def _make_tool_call_stream_events():
    """Tool call: model calls 'get_weather' tool, then responds with text."""
    ai_msg_id = "ai-msg-1"
    tool_call_id = "call_abc123"

    # Step 1: Model streams tool call chunks
    yield (
        "messages",
        (
            AIMessageChunk(
                content="",
                id=ai_msg_id,
                tool_call_chunks=[
                    {"id": tool_call_id, "name": "get_weather", "args": '{"city":', "index": 0}
                ],
            ),
            {"langgraph_step": 1, "langgraph_node": "model"},
        ),
    )
    yield (
        "messages",
        (
            AIMessageChunk(
                content="",
                id=ai_msg_id,
                tool_call_chunks=[
                    {"id": None, "name": None, "args": ' "Paris"}', "index": 0}
                ],
            ),
            {"langgraph_step": 1, "langgraph_node": "model"},
        ),
    )

    # Values after model step: includes tool call in full message
    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="weather in Paris?", id="user-msg-1"),
                AIMessage(
                    content="",
                    id=ai_msg_id,
                    tool_calls=[
                        {"id": tool_call_id, "name": "get_weather", "args": {"city": "Paris"}}
                    ],
                ),
            ]
        },
    )

    # Step 2: Tool output arrives
    yield (
        "messages",
        (
            ToolMessage(
                content='{"temperature": 22, "unit": "celsius"}',
                tool_call_id=tool_call_id,
                id="tool-msg-1",
            ),
            {"langgraph_step": 2, "langgraph_node": "tools"},
        ),
    )

    # Values after tool step
    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="weather in Paris?", id="user-msg-1"),
                AIMessage(
                    content="",
                    id=ai_msg_id,
                    tool_calls=[
                        {"id": tool_call_id, "name": "get_weather", "args": {"city": "Paris"}}
                    ],
                ),
                ToolMessage(
                    content='{"temperature": 22, "unit": "celsius"}',
                    tool_call_id=tool_call_id,
                    id="tool-msg-1",
                ),
            ]
        },
    )

    # Step 3: Model responds with text
    yield (
        "messages",
        (
            AIMessageChunk(content="The weather in Paris is 22°C.", id="ai-msg-2"),
            {"langgraph_step": 3, "langgraph_node": "model"},
        ),
    )

    # Final values
    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="weather in Paris?", id="user-msg-1"),
                AIMessage(
                    content="",
                    id=ai_msg_id,
                    tool_calls=[
                        {"id": tool_call_id, "name": "get_weather", "args": {"city": "Paris"}}
                    ],
                ),
                ToolMessage(
                    content='{"temperature": 22, "unit": "celsius"}',
                    tool_call_id=tool_call_id,
                    id="tool-msg-1",
                ),
                AIMessage(content="The weather in Paris is 22°C.", id="ai-msg-2"),
            ]
        },
    )


def _make_hitl_interrupt_events():
    """HITL: model calls tool that needs approval, stream interrupts."""
    ai_msg_id = "ai-msg-1"
    tool_call_id = "call_needs_approval"

    # Model streams tool call
    yield (
        "messages",
        (
            AIMessageChunk(
                content="",
                id=ai_msg_id,
                tool_call_chunks=[
                    {"id": tool_call_id, "name": "delete_file", "args": '{"path": "/tmp/test"}', "index": 0}
                ],
            ),
            {"langgraph_step": 1, "langgraph_node": "model"},
        ),
    )

    # Values with interrupt
    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="delete /tmp/test", id="user-msg-1"),
                AIMessage(
                    content="",
                    id=ai_msg_id,
                    tool_calls=[
                        {"id": tool_call_id, "name": "delete_file", "args": {"path": "/tmp/test"}}
                    ],
                ),
            ],
            "__interrupt__": [
                {
                    "value": {
                        "action_requests": [
                            {"name": "delete_file", "args": {"path": "/tmp/test"}}
                        ]
                    }
                }
            ],
        },
    )


async def _async_gen(events):
    for event in events:
        yield event


# ── Tests ──────────────────────────────────────────────────────────────


async def test_basic_text_stream():
    """Text-only conversation produces start → text events → finish → done."""
    adapter = AISDKStreamAdapter()
    events = []
    async for sse in adapter.stream(_async_gen(_make_text_stream_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]

    # First event: start with messageId
    assert parsed[0]["type"] == "start"
    assert "messageId" in parsed[0]

    # Should have text-start, text-delta(s), text-end
    types = [p["type"] for p in parsed if p is not None]
    assert "text-start" in types
    assert "text-delta" in types
    assert "text-end" in types

    # Last events: finish + [DONE]
    assert parsed[-2]["type"] == "finish"
    assert parsed[-1] is None  # [DONE]

    # Concatenated text
    text = "".join(p["delta"] for p in parsed if p and p["type"] == "text-delta")
    assert "Hello" in text


async def test_tool_call_stream():
    """Tool call produces tool-input-start → tool-input-available → tool-output-available."""
    adapter = AISDKStreamAdapter()
    events = []
    async for sse in adapter.stream(_async_gen(_make_tool_call_stream_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]
    types = [p["type"] for p in parsed if p is not None]

    assert "tool-input-start" in types
    assert "tool-input-available" in types
    assert "tool-output-available" in types

    # Check tool-input-start has correct tool name
    tool_start = next(p for p in parsed if p and p["type"] == "tool-input-start")
    assert tool_start["toolName"] == "get_weather"

    # Check tool-output-available
    tool_output = next(p for p in parsed if p and p["type"] == "tool-output-available")
    assert tool_output["toolCallId"] is not None

    # Should also have text from the model's final response
    assert "text-delta" in types


async def test_hitl_interrupt_suppresses_finish():
    """When HITL is pending, finish is suppressed and only [DONE] is emitted."""
    adapter = AISDKStreamAdapter()
    events = []
    async for sse in adapter.stream(_async_gen(_make_hitl_interrupt_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]
    types = [p["type"] for p in parsed if p is not None]

    # Should have tool-approval-request
    assert "tool-approval-request" in types

    # finish should NOT be present
    assert "finish" not in types

    # [DONE] should still be present
    assert events[-1].strip() == "data: [DONE]"


async def test_rejected_tool_replay():
    """Rejected tool calls are replayed as tool-output-error at stream start."""
    adapter = AISDKStreamAdapter(
        rejected_tool_calls=[
            {"toolCallId": "call_rejected", "toolName": "rm_rf", "reason": "Too dangerous"},
        ],
    )
    events = []
    async for sse in adapter.stream(_async_gen(_make_text_stream_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]

    # First event: start
    assert parsed[0]["type"] == "start"

    # Second event: tool-output-error for the rejected tool
    assert parsed[1]["type"] == "tool-output-error"
    assert parsed[1]["toolCallId"] == "call_rejected"
    assert parsed[1]["errorText"] == "Too dangerous"


async def test_provider_metadata_injection():
    """providerMetadata is injected on tool-input events when tool_ui_metadata is set."""
    adapter = AISDKStreamAdapter(
        tool_ui_metadata={
            "get_weather": {
                "mcp_app_resource_uri": "resource://weather/dashboard",
                "mcp_server_id": "server-123",
            }
        }
    )
    events = []
    async for sse in adapter.stream(_async_gen(_make_tool_call_stream_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]

    # Find tool-input-start for get_weather
    tool_starts = [p for p in parsed if p and p["type"] == "tool-input-start" and p.get("toolName") == "get_weather"]
    assert len(tool_starts) > 0
    assert tool_starts[0]["providerMetadata"] == {
        "auxilia": {
            "mcpAppResourceUri": "resource://weather/dashboard",
            "mcpServerId": "server-123",
        }
    }


async def test_structured_content_wrapping():
    """Structured content from ToolMessage.artifact wraps the output."""

    async def stream_with_artifact():
        ai_msg_id = "ai-msg-1"
        tool_call_id = "call_sc"

        yield ("messages", (
            AIMessageChunk(
                content="",
                id=ai_msg_id,
                tool_call_chunks=[
                    {"id": tool_call_id, "name": "render_chart", "args": '{}', "index": 0}
                ],
            ),
            {"langgraph_step": 1},
        ))

        yield ("values", {
            "messages": [
                AIMessage(content="", id=ai_msg_id, tool_calls=[
                    {"id": tool_call_id, "name": "render_chart", "args": {}}
                ]),
            ]
        })

        yield ("messages", (
            ToolMessage(
                content="[Chart rendered]",
                tool_call_id=tool_call_id,
                id="tool-msg-1",
                artifact={"structured_content": {"type": "chart", "data": [1, 2, 3]}},
            ),
            {"langgraph_step": 2},
        ))

        yield ("values", {
            "messages": [
                AIMessage(content="", id=ai_msg_id, tool_calls=[
                    {"id": tool_call_id, "name": "render_chart", "args": {}}
                ]),
                ToolMessage(
                    content="[Chart rendered]",
                    tool_call_id=tool_call_id,
                    id="tool-msg-1",
                    artifact={"structured_content": {"type": "chart", "data": [1, 2, 3]}},
                ),
            ]
        })

    adapter = AISDKStreamAdapter()
    events = []
    async for sse in adapter.stream(stream_with_artifact()):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]
    tool_outputs = [p for p in parsed if p and p["type"] == "tool-output-available"]
    assert len(tool_outputs) > 0

    output = tool_outputs[0]["output"]
    assert isinstance(output, dict)
    assert output["_text"] == "[Chart rendered]"
    assert output["structuredContent"] == {"type": "chart", "data": [1, 2, 3]}


async def test_message_id_injection():
    """Custom messageId is set on the start event."""
    adapter = AISDKStreamAdapter(message_id="custom-msg-id")
    events = []
    async for sse in adapter.stream(_async_gen(_make_text_stream_events())):
        events.append(sse)

    parsed = [_parse_sse(e) for e in events]
    assert parsed[0]["type"] == "start"
    assert parsed[0]["messageId"] == "custom-msg-id"


# ── Slack adapter tests ──────────────────────────────────────────────


async def test_slack_text_stream():
    """Slack adapter yields text events."""
    adapter = SlackStreamAdapter()
    events = []
    async for event in adapter.stream(_async_gen(_make_text_stream_events())):
        events.append(event)

    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) > 0
    full_text = "".join(e["content"] for e in text_events)
    assert "Hello" in full_text


async def test_slack_tool_events():
    """Slack adapter yields tool_start and tool_end events with enriched info."""
    adapter = SlackStreamAdapter()
    events = []
    async for event in adapter.stream(_async_gen(_make_tool_call_stream_events())):
        events.append(event)

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool_name"] == "get_weather"

    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["tool_name"] == "get_weather"
    assert tool_end["output"] is not None
