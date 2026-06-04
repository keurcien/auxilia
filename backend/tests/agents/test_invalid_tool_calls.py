"""Tests for RepairInvalidToolCallsMiddleware.

The model can emit tool-call arguments that aren't valid JSON (a large payload
truncated or duplicated). Providers route those to ``invalid_tool_calls`` and
the agent would otherwise exit the loop silently. The middleware turns each into
an error ToolMessage and loops back to the model.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import invalid_tool_call, tool_call

from app.agents.invalid_tool_calls import (
    MAX_ECHOED_ARGS_CHARS,
    RepairInvalidToolCallsMiddleware,
)


def _run(messages):
    middleware = RepairInvalidToolCallsMiddleware()
    return middleware.after_model({"messages": messages}, runtime=None)


def test_no_invalid_tool_calls_is_noop():
    messages = [
        HumanMessage(content="hi", id="h1"),
        AIMessage(content="hello", id="a1"),
    ]
    assert _run(messages) is None


def test_valid_tool_calls_untouched():
    ai = AIMessage(
        content="",
        id="a1",
        tool_calls=[tool_call(name="get_weather", args={"city": "Paris"}, id="c1")],
    )
    assert _run([ai]) is None


def test_invalid_tool_call_becomes_error_tool_message():
    ai = AIMessage(
        content="",
        id="a1",
        invalid_tool_calls=[
            invalid_tool_call(
                name="notion-create-pages",
                args='{"pages": [...]}}}{"pages"',
                id="call_bad",
                error="Extra data: line 1 column 10586 (char 10585)",
            )
        ],
    )

    result = _run([HumanMessage(content="make a page", id="h1"), ai])

    # Loops back to the model so it can read the error and retry.
    assert result["jump_to"] == "model"

    repaired_ai, tool_msg = result["messages"]

    # The offending AIMessage is replaced in place (same id) with a well-formed
    # tool call and no lingering invalid calls.
    assert isinstance(repaired_ai, AIMessage)
    assert repaired_ai.id == "a1"
    assert repaired_ai.invalid_tool_calls == []
    assert len(repaired_ai.tool_calls) == 1
    assert repaired_ai.tool_calls[0]["id"] == "call_bad"
    assert repaired_ai.tool_calls[0]["name"] == "notion-create-pages"
    assert repaired_ai.tool_calls[0]["args"] == {}

    # The error is answered as a tool result keyed to the same call id.
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_bad"
    assert tool_msg.status == "error"
    assert "notion-create-pages" in tool_msg.content
    assert "Extra data" in tool_msg.content
    assert "not valid JSON" in tool_msg.content


def test_preserves_valid_calls_alongside_invalid():
    ai = AIMessage(
        content="",
        id="a1",
        tool_calls=[tool_call(name="search", args={"q": "x"}, id="ok")],
        invalid_tool_calls=[
            invalid_tool_call(name="write", args="{bad", id="bad", error="boom")
        ],
    )

    result = _run([ai])
    repaired_ai = result["messages"][0]
    ids = {tc["id"] for tc in repaired_ai.tool_calls}
    assert ids == {"ok", "bad"}
    # One error tool message, for the invalid call only.
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "bad"


def test_large_args_are_truncated_in_echo():
    huge = "{" + "a" * (MAX_ECHOED_ARGS_CHARS + 500)
    ai = AIMessage(
        content="",
        id="a1",
        invalid_tool_calls=[
            invalid_tool_call(name="t", args=huge, id="c1", error="boom")
        ],
    )

    result = _run([ai])
    content = result["messages"][1].content
    assert "truncated" in content
    # The full payload is not echoed back verbatim.
    assert huge not in content


def test_missing_id_gets_synthesized():
    ai = AIMessage(
        content="",
        id="a1",
        invalid_tool_calls=[
            invalid_tool_call(name="t", args="{bad", id=None, error="boom")
        ],
    )

    result = _run([ai])
    repaired_ai, tool_msg = result["messages"]
    assert repaired_ai.tool_calls[0]["id"]  # non-empty
    assert tool_msg.tool_call_id == repaired_ai.tool_calls[0]["id"]
