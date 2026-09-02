"""ProtocolTranslator: legacy SSE log → Agent Streaming Protocol events.

Fixtures are driven through the real `LangGraphStreamAdapter` (the worker's
encoder) and decoded back, so these tests exercise the actual wire boundary
the facade reads — the same pattern as `tests/agents/test_stream.py`.
"""

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.protocol.translate import ProtocolTranslator
from app.agents.runs.state import RunStatus
from app.agents.stream import LangGraphStreamAdapter, decode_sse_blocks


async def _translate(events, *, subgraphs=False, status=RunStatus.success):
    """Run raw astream tuples through encoder → decoder → translator."""

    async def _gen():
        for event in events:
            yield event

    translator = ProtocolTranslator()
    out = []
    async for sse in LangGraphStreamAdapter(subgraphs=subgraphs).stream(_gen()):
        for event_name, data in decode_sse_blocks(sse):
            out.extend(translator.translate(event_name, data))
    out.extend(translator.finish(status))
    return out


def _data(event):
    return event["params"]["data"]


def _of(events, method):
    return [e for e in events if e["method"] == method]


async def test_text_stream_becomes_message_deltas():
    msg_id = "ai-1"
    events = await _translate(
        [
            (
                "messages",
                (AIMessageChunk(content="", id=msg_id), {"langgraph_node": "model"}),
            ),
            (
                "messages",
                (AIMessageChunk(content="Hel", id=msg_id), {"langgraph_node": "model"}),
            ),
            (
                "messages",
                (AIMessageChunk(content="lo", id=msg_id), {"langgraph_node": "model"}),
            ),
        ]
    )

    messages = _of(events, "messages")
    kinds = [_data(e)["event"] for e in messages]
    assert kinds == [
        "message-start",
        "content-block-start",
        "content-block-delta",
        "message-finish",
    ]
    start = _data(messages[0])
    assert start["role"] == "ai"
    assert start["id"] == msg_id
    assert _data(messages[1])["content"] == {"type": "text", "text": "Hel"}
    assert _data(messages[2])["delta"] == {"type": "text-delta", "text": "lo"}

    lifecycle = [_data(e)["event"] for e in _of(events, "lifecycle")]
    assert lifecycle == ["started", "completed"]


async def test_values_snapshot_is_trimmed_and_interrupt_becomes_input_requested():
    events = await _translate(
        [
            (
                "values",
                {
                    "messages": [HumanMessage(content="hi", id="u1")],
                    "todos": [{"content": "step", "status": "pending"}],
                    "__interrupt__": [
                        {"id": "int-1", "value": {"action_requests": []}}
                    ],
                },
            )
        ],
        status=RunStatus.interrupted,
    )

    [values] = _of(events, "values")
    assert values["params"]["namespace"] == []
    assert "messages" not in _data(values)
    assert "__interrupt__" not in _data(values)
    assert _data(values)["todos"] == [{"content": "step", "status": "pending"}]

    [requested] = _of(events, "input.requested")
    assert _data(requested)["interrupt_id"] == "int-1"
    assert _data(requested)["payload"] == {"action_requests": []}

    assert [_data(e)["event"] for e in _of(events, "lifecycle")] == [
        "started",
        "interrupted",
    ]


async def test_tool_call_lifecycle():
    """Streamed tool-call chunks assemble into a finalized tool_call block;
    `updates` yields tool-started; the ToolMessage yields the tool-role
    message and tool-finished."""
    ai_id, tc_id = "ai-1", "call-1"
    ai_final = AIMessage(
        content="",
        id=ai_id,
        tool_calls=[{"id": tc_id, "name": "get_weather", "args": {"city": "Paris"}}],
    )
    events = await _translate(
        [
            (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        id=ai_id,
                        tool_call_chunks=[
                            {
                                "id": tc_id,
                                "name": "get_weather",
                                "args": '{"city":',
                                "index": 0,
                            }
                        ],
                    ),
                    {"langgraph_node": "model"},
                ),
            ),
            (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        id=ai_id,
                        tool_call_chunks=[
                            {"id": None, "name": None, "args": ' "Paris"}', "index": 0}
                        ],
                    ),
                    {"langgraph_node": "model"},
                ),
            ),
            ("updates", {"agent": {"messages": [ai_final]}}),
            (
                "messages",
                (
                    ToolMessage(
                        content='{"temperature": 22}', tool_call_id=tc_id, id="tm-1"
                    ),
                    {"langgraph_node": "tools"},
                ),
            ),
        ]
    )

    tools = _of(events, "tools")
    assert [_data(e)["event"] for e in tools] == ["tool-started", "tool-finished"]
    started, finished = _data(tools[0]), _data(tools[1])
    assert started["tool_call_id"] == tc_id
    assert started["tool_name"] == "get_weather"
    assert started["input"] == {"city": "Paris"}
    assert finished["output"] == '{"temperature": 22}'

    # The streamed chunks were sealed into a parsed tool_call block when the
    # superstep boundary (the updates event) closed the message.
    finishes = [
        _data(e)
        for e in _of(events, "messages")
        if _data(e)["event"] == "content-block-finish"
    ]
    assert any(
        f["content"]["type"] == "tool_call"
        and f["content"]["id"] == tc_id
        and f["content"]["args"] == {"city": "Paris"}
        for f in finishes
    )

    # The ToolMessage rides the messages channel as a tool-role message.
    tool_starts = [
        _data(e)
        for e in _of(events, "messages")
        if _data(e)["event"] == "message-start" and _data(e)["role"] == "tool"
    ]
    assert tool_starts and tool_starts[0]["tool_call_id"] == tc_id


async def test_tool_error_message_becomes_tool_error():
    events = await _translate(
        [
            (
                "messages",
                (
                    ToolMessage(
                        content="boom",
                        tool_call_id="call-1",
                        id="tm-1",
                        status="error",
                    ),
                    {"langgraph_node": "tools"},
                ),
            )
        ],
        status=RunStatus.error,
    )
    [error] = _of(events, "tools")
    assert _data(error)["event"] == "tool-error"
    assert _data(error)["message"] == "boom"


async def test_deepseek_reasoning_rides_a_reasoning_block():
    msg_id = "ai-1"
    chunk = AIMessageChunk(
        content="", id=msg_id, additional_kwargs={"reasoning_content": "hmm"}
    )
    chunk2 = AIMessageChunk(
        content="", id=msg_id, additional_kwargs={"reasoning_content": " more"}
    )
    events = await _translate(
        [
            ("messages", (chunk, {"langgraph_node": "model"})),
            ("messages", (chunk2, {"langgraph_node": "model"})),
        ]
    )
    messages = _of(events, "messages")
    kinds = [_data(e)["event"] for e in messages]
    assert kinds == [
        "message-start",
        "content-block-start",
        "content-block-delta",
        "message-finish",
    ]
    assert _data(messages[1])["content"] == {"type": "reasoning", "reasoning": "hmm"}
    assert _data(messages[2])["delta"] == {
        "type": "reasoning-delta",
        "reasoning": " more",
    }


async def test_subagent_namespace_values_keep_only_the_binding_message():
    """Namespaced values keep the first human message on the first snapshot
    (the client binds `tools:<task-id>` namespaces to their `task` call by
    that text) and drop messages afterwards."""
    ns = ("tools:task-1",)
    first = {
        "messages": [
            HumanMessage(content="research X", id="h1"),
            AIMessage(content="on it", id="a1"),
        ]
    }
    second = {
        "messages": [
            HumanMessage(content="research X", id="h1"),
            AIMessage(content="done", id="a2"),
        ],
        "todos": [],
    }
    events = await _translate(
        [(ns, "values", first), (ns, "values", second)], subgraphs=True
    )

    values = _of(events, "values")
    assert len(values) == 2
    first_msgs = _data(values[0]).get("messages")
    assert first_msgs is not None and len(first_msgs) == 1
    assert first_msgs[0]["content"] == "research X"
    assert "messages" not in _data(values[1])

    # The namespace's first event also announced its lifecycle.
    ns_lifecycles = [
        e
        for e in _of(events, "lifecycle")
        if e["params"]["namespace"] == ["tools:task-1"]
    ]
    assert ns_lifecycles and _data(ns_lifecycles[0])["event"] == "started"


async def test_error_event_becomes_lifecycle_failed():
    async def _gen():
        yield ("messages", (AIMessageChunk(content="x", id="m1"), {}))
        raise ValueError("boom")

    translator = ProtocolTranslator()
    out = []
    async for sse in LangGraphStreamAdapter(subgraphs=False).stream(_gen()):
        for event_name, data in decode_sse_blocks(sse):
            out.extend(translator.translate(event_name, data))

    failed = [
        e
        for e in _of(out, "lifecycle")
        if _data(e)["event"] == "failed" and e["params"]["namespace"] == []
    ]
    assert failed and _data(failed[0])["error"] == "boom"
    # The in-flight message was sealed before the failure surfaced.
    assert any(_data(e)["event"] == "message-finish" for e in _of(out, "messages"))


async def test_new_message_id_on_same_node_closes_the_previous_message():
    events = await _translate(
        [
            (
                "messages",
                (AIMessageChunk(content="one", id="m1"), {"langgraph_node": "model"}),
            ),
            (
                "messages",
                (AIMessageChunk(content="two", id="m2"), {"langgraph_node": "model"}),
            ),
        ]
    )
    kinds = [
        (_data(e)["event"], _data(e).get("id"))
        for e in _of(events, "messages")
        if _data(e)["event"] in ("message-start", "message-finish")
    ]
    assert kinds == [
        ("message-start", "m1"),
        ("message-finish", None),
        ("message-start", "m2"),
        ("message-finish", None),
    ]


async def test_cancelled_run_finishes_as_completed_lifecycle():
    translator = ProtocolTranslator()
    events = translator.finish(RunStatus.cancelled)
    assert [(e["method"], _data(e)["event"]) for e in events] == [
        ("lifecycle", "completed")
    ]


async def test_finish_after_an_error_event_adds_no_second_terminal():
    """The error event is the terminal that carries the message; the worker's
    end sentinel (status=error) that follows must not add a second one."""

    async def _gen():
        yield ("messages", (AIMessageChunk(content="x", id="m1"), {}))
        raise ValueError("boom")

    translator = ProtocolTranslator()
    out = []
    async for sse in LangGraphStreamAdapter(subgraphs=False).stream(_gen()):
        for event_name, data in decode_sse_blocks(sse):
            out.extend(translator.translate(event_name, data))
    out.extend(translator.finish(RunStatus.error))

    terminals = [
        _data(e)
        for e in _of(out, "lifecycle")
        if _data(e)["event"] in ("completed", "failed", "interrupted")
    ]
    assert len(terminals) == 1
    assert terminals[0] == {"event": "failed", "error": "boom"}
