from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.stream import SlackStreamAdapter


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


async def _async_gen(events):
    for event in events:
        yield event


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
