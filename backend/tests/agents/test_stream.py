from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.stream import LangGraphStreamAdapter, SlackStreamAdapter


# ── Fixtures: LangGraph astream(stream_mode=["messages", "values"]) tuples ──
#
# The worker publishes LangGraph-native SSE to the run event log; the Slack
# consumer reads that same SSE back. So these tests drive the fixtures through
# `LangGraphStreamAdapter` (worker side) and feed the resulting SSE strings into
# `SlackStreamAdapter` (consumer side) — exercising the real wire boundary.


def _make_text_stream_events():
    """Simple text conversation: model streams 'Hello! How can I assist you today?'"""
    msg_id = "lc_run--019cd8c3-7104-7173-9361-b7f162dfa28c"

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

    yield (
        "values",
        {
            "messages": [
                HumanMessage(content="hi", id="user-msg-1"),
                AIMessage(content="Hello! How can I assist you today?", id=msg_id),
            ]
        },
    )


def _make_tool_call_stream_events():
    """Tool call: model calls 'get_weather', then responds with text."""
    ai_msg_id = "ai-msg-1"
    tool_call_id = "call_abc123"

    yield (
        "messages",
        (
            AIMessageChunk(
                content="",
                id=ai_msg_id,
                tool_call_chunks=[
                    {
                        "id": tool_call_id,
                        "name": "get_weather",
                        "args": '{"city":',
                        "index": 0,
                    }
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
    yield (
        "messages",
        (
            ToolMessage(
                content='{"temperature": 22}',
                tool_call_id=tool_call_id,
                id="tool-msg-1",
            ),
            {"langgraph_step": 2, "langgraph_node": "tools"},
        ),
    )
    yield (
        "messages",
        (
            AIMessageChunk(content="The weather in Paris is 22°C.", id="ai-msg-2"),
            {"langgraph_step": 3, "langgraph_node": "model"},
        ),
    )


async def _async_gen(events):
    for event in events:
        yield event


async def _to_sse(events):
    """Run worker-side LangGraph fixtures through the SSE encoder."""
    async for sse in LangGraphStreamAdapter(subgraphs=False).stream(_async_gen(events)):
        yield sse


async def _collect(adapter_stream):
    return [event async for event in adapter_stream]


# ── Slack adapter tests (SSE event log → typed Slack events) ─────────────


async def test_slack_text_stream():
    """Text deltas in the messages SSE become Slack text events."""
    events = await _collect(
        SlackStreamAdapter().stream(_to_sse(_make_text_stream_events()))
    )

    text_events = [e for e in events if e["type"] == "text"]
    assert text_events
    assert "Hello" in "".join(e["content"] for e in text_events)


async def test_slack_tool_start_emitted_once():
    """A streamed tool call yields a single tool_start with the tool name."""
    events = await _collect(
        SlackStreamAdapter().stream(_to_sse(_make_tool_call_stream_events()))
    )

    tool_starts = [e for e in events if e["type"] == "tool_start"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["tool_name"] == "get_weather"
    assert tool_starts[0]["tool_call_id"] == "call_abc123"
    # The consumer derives approvals from the checkpoint, not the stream.
    assert all(e["type"] != "tool_approval_request" for e in events)

    # The model's final answer streams as text...
    streamed = "".join(e["content"] for e in events if e["type"] == "text")
    assert "The weather in Paris is 22°C." in streamed
    # ...but the raw tool-result ToolMessage must NOT be dumped as text.
    assert "temperature" not in streamed


async def test_slack_tool_message_content_is_not_streamed():
    """A ToolMessage in the messages stream is not surfaced as assistant text."""
    tool_sse = (
        "event: messages\n"
        'data: [{"type": "tool", "content": "{\\"secret\\": 42}", '
        '"id": "tm-1", "tool_call_id": "call_1"}, {}]\n\n'
    )
    events = await _collect(SlackStreamAdapter().stream(_async_gen([tool_sse])))

    assert events == []


async def test_slack_end_event_carries_status():
    """The terminal sentinel is surfaced as an `end` event with its status."""
    sentinel = 'event: end\ndata: {"status": "interrupted"}\n\n'
    events = await _collect(SlackStreamAdapter().stream(_async_gen([sentinel])))

    assert events == [{"type": "end", "status": "interrupted"}]


async def test_slack_error_event():
    """An error SSE becomes a Slack error event with the message."""
    err = 'event: error\ndata: {"message": "boom", "status_code": 500}\n\n'
    events = await _collect(SlackStreamAdapter().stream(_async_gen([err])))

    assert events == [{"type": "error", "content": "boom"}]


async def test_slack_subagent_messages_are_skipped():
    """Namespaced (subagent) messages events are not streamed to Slack."""
    ns = (
        "event: messages|tools:abc\n"
        'data: [{"type": "AIMessageChunk", "content": "secret", "id": "x"}, {}]\n\n'
    )
    events = await _collect(SlackStreamAdapter().stream(_async_gen([ns])))

    assert events == []
