from types import SimpleNamespace

from langchain_ai_sdk_adapter import to_lc_messages
from langchain_core.messages import AIMessage, HumanMessage

from app.threads.serialization import pending_approval_requests


async def test_to_lc_messages():
    messages = [
        {"id": "1", "role": "user", "parts": [{"type": "text", "text": "Lorem ipsum"}]}
    ]
    langchain_messages = await to_lc_messages(messages)
    assert len(langchain_messages) == 1
    assert isinstance(langchain_messages[0], HumanMessage)
    assert langchain_messages[0].content == "Lorem ipsum"


def _checkpoint(interrupt_value, messages):
    """A minimal checkpoint tuple: `pending_writes` + `checkpoint.channel_values`."""
    pending_writes = (
        [("task-1", "__interrupt__", [SimpleNamespace(value=interrupt_value)])]
        if interrupt_value is not None
        else []
    )
    return SimpleNamespace(
        pending_writes=pending_writes,
        checkpoint={"channel_values": {"messages": messages}},
    )


def test_pending_approval_requests_maps_action_requests_to_tool_call_ids():
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}}],
    )
    interrupt_value = {
        "action_requests": [
            {"name": "get_weather", "args": {"city": "Paris"}, "description": "review"}
        ],
        "review_configs": [
            {"action_name": "get_weather", "allowed_decisions": ["approve"]}
        ],
    }

    out = pending_approval_requests(_checkpoint(interrupt_value, [ai]))

    assert out == [
        {
            "tool_call_id": "call_1",
            "tool_name": "get_weather",
            "input": {"city": "Paris"},
        }
    ]


def test_pending_approval_requests_empty_when_not_interrupted():
    assert pending_approval_requests(_checkpoint(None, [])) == []


def test_pending_approval_requests_synthesizes_id_without_match():
    # Interrupt with no matching tool call still yields a usable approval entry.
    interrupt_value = {"action_requests": [{"name": "send_email", "args": {}}]}
    out = pending_approval_requests(_checkpoint(interrupt_value, []))
    assert out == [
        {"tool_call_id": "approval-0", "tool_name": "send_email", "input": {}}
    ]
