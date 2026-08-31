"""HITL checkpoint reading + resume-command canonicalization (`app/agents/hitl.py`)."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.agents.hitl import (
    build_resume_command,
    is_addressed_resume,
    pending_approval_requests,
    pending_interrupt,
)
from app.exceptions import DomainValidationError, StaleApprovalError


INTERRUPT_ID = "ab" * 16  # 32 hex chars — the xxh3-128 shape langgraph emits


def _checkpoint(interrupt_value, messages, interrupt_id=INTERRUPT_ID):
    """A minimal checkpoint tuple: `pending_writes` + `checkpoint.channel_values`."""
    pending_writes = (
        [
            (
                "task-1",
                "__interrupt__",
                [SimpleNamespace(value=interrupt_value, id=interrupt_id)],
            )
        ]
        if interrupt_value is not None
        else []
    )
    return SimpleNamespace(
        pending_writes=pending_writes,
        checkpoint={"channel_values": {"messages": messages}},
    )


def _two_call_checkpoint():
    """A paused checkpoint with two tool calls awaiting approval."""
    ai = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}},
            {"id": "call_2", "name": "send_email", "args": {"to": "a@b.c"}},
        ],
    )
    interrupt_value = {
        "action_requests": [
            {"name": "get_weather", "args": {"city": "Paris"}},
            {"name": "send_email", "args": {"to": "a@b.c"}},
        ],
    }
    return _checkpoint(interrupt_value, [ai])


# ---------------------------------------------------------------------------
# pending_interrupt — the id must survive the read
# ---------------------------------------------------------------------------


def test_pending_interrupt_keeps_the_id():
    out = pending_interrupt(_checkpoint({"action_requests": []}, []))
    assert out is not None
    assert out.id == INTERRUPT_ID
    assert out.value == {"action_requests": []}


def test_pending_interrupt_none_when_not_interrupted():
    assert pending_interrupt(_checkpoint(None, [])) is None
    assert pending_interrupt(None) is None  # no checkpoint at all


def test_pending_interrupt_tolerates_dict_shape():
    # A serde that didn't round-trip the Interrupt object yields a plain dict.
    cp = SimpleNamespace(
        pending_writes=[
            ("t", "__interrupt__", [{"value": {"a": 1}, "id": INTERRUPT_ID}])
        ],
        checkpoint={"channel_values": {}},
    )
    out = pending_interrupt(cp)
    assert out == (INTERRUPT_ID, {"a": 1})


def test_pending_interrupt_id_none_when_absent():
    out = pending_interrupt(_checkpoint({"action_requests": []}, [], interrupt_id=None))
    assert out is not None
    assert out.id is None


# ---------------------------------------------------------------------------
# pending_approval_requests (moved from threads/serialization — same contract)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# build_resume_command — order from the checkpoint, staleness rejected
# ---------------------------------------------------------------------------


def test_addressed_resume_is_ordered_by_the_checkpoint_not_the_client():
    # Decisions supplied in reversed order must land in action_requests order.
    resume = {
        "interrupt_id": INTERRUPT_ID,
        "decisions": [
            {"tool_call_id": "call_2", "type": "reject"},
            {"tool_call_id": "call_1", "type": "approve"},
        ],
    }
    out = build_resume_command(_two_call_checkpoint(), resume)
    assert out == {
        "resume": {
            INTERRUPT_ID: {"decisions": [{"type": "approve"}, {"type": "reject"}]}
        }
    }


def test_stale_when_nothing_is_pending():
    resume = {"interrupt_id": INTERRUPT_ID, "decisions": []}
    with pytest.raises(StaleApprovalError):
        build_resume_command(_checkpoint(None, []), resume)
    with pytest.raises(StaleApprovalError):
        build_resume_command(None, resume)


def test_stale_when_a_different_interrupt_pends():
    resume = {
        "interrupt_id": "cd" * 16,
        "decisions": [{"tool_call_id": "call_1", "type": "approve"}],
    }
    with pytest.raises(StaleApprovalError):
        build_resume_command(_two_call_checkpoint(), resume)


def test_decisions_must_cover_the_pending_requests_exactly():
    incomplete = {
        "interrupt_id": INTERRUPT_ID,
        "decisions": [{"tool_call_id": "call_1", "type": "approve"}],
    }
    with pytest.raises(DomainValidationError):
        build_resume_command(_two_call_checkpoint(), incomplete)

    unknown = {
        "interrupt_id": INTERRUPT_ID,
        "decisions": [
            {"tool_call_id": "call_1", "type": "approve"},
            {"tool_call_id": "call_2", "type": "approve"},
            {"tool_call_id": "call_9", "type": "approve"},
        ],
    }
    with pytest.raises(DomainValidationError):
        build_resume_command(_two_call_checkpoint(), unknown)


def test_decision_without_tool_call_id_is_rejected():
    resume = {"interrupt_id": INTERRUPT_ID, "decisions": [{"type": "approve"}]}
    with pytest.raises(DomainValidationError):
        build_resume_command(_two_call_checkpoint(), resume)


def test_extra_decision_fields_survive_for_edit_and_respond():
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "send_email", "args": {}}],
    )
    cp = _checkpoint({"action_requests": [{"name": "send_email", "args": {}}]}, [ai])
    resume = {
        "interrupt_id": INTERRUPT_ID,
        "decisions": [
            {"tool_call_id": "call_1", "type": "reject", "message": "not now"}
        ],
    }
    out = build_resume_command(cp, resume)
    assert out["resume"][INTERRUPT_ID]["decisions"] == [
        {"type": "reject", "message": "not now"}
    ]


@pytest.mark.parametrize("checkpoint_id", [None, "placeholder-id"])
def test_unusable_interrupt_id_falls_back_to_the_plain_resume_form(checkpoint_id):
    """A checkpoint without a map-safe id (missing, or langgraph's placeholder,
    which `Command(resume=...)` would not detect as an id map) still resumes —
    via the plain form, which targets the single pending interrupt. (With an
    id-less checkpoint the stale check is skipped; a placeholder id still
    participates in it, so the client echoes it.)"""
    ai = AIMessage(content="", tool_calls=[{"id": "call_1", "name": "t", "args": {}}])
    cp = _checkpoint(
        {"action_requests": [{"name": "t", "args": {}}]},
        [ai],
        interrupt_id=checkpoint_id,
    )
    resume = {
        "interrupt_id": checkpoint_id or INTERRUPT_ID,
        "decisions": [{"tool_call_id": "call_1", "type": "approve"}],
    }
    out = build_resume_command(cp, resume)
    assert out == {"resume": {"decisions": [{"type": "approve"}]}}


def test_is_addressed_resume():
    assert is_addressed_resume({"interrupt_id": "x", "decisions": []})
    assert not is_addressed_resume({"decisions": [{"type": "approve"}]})  # legacy
    assert not is_addressed_resume({INTERRUPT_ID: {"decisions": []}})  # canonical
    assert not is_addressed_resume("free-form")
    assert not is_addressed_resume(None)


# ---------------------------------------------------------------------------
# End to end against a real graph: the id we extract IS the resume-map key
# ---------------------------------------------------------------------------


async def test_extracted_id_resumes_a_real_graph_via_the_map_form():
    """The whole contract in one place: a paused graph's checkpoint yields an
    id through `pending_interrupt`, and `Command(resume={id: ...})` — the
    shape `build_resume_command` emits — resumes exactly that interrupt."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command, interrupt
    from typing_extensions import TypedDict

    class State(TypedDict):
        answer: str

    def node(state: State) -> State:
        decision = interrupt({"action_requests": [{"name": "t", "args": {}}]})
        return {"answer": decision["decisions"][0]["type"]}

    builder = StateGraph(State)
    builder.add_node("node", node)
    builder.add_edge(START, "node")
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-hitl"}}

    await graph.ainvoke({"answer": ""}, config)  # pauses on the interrupt

    checkpoint = await graph.checkpointer.aget_tuple(config)
    pending = pending_interrupt(checkpoint)
    assert pending is not None
    assert pending.id is not None

    command = build_resume_command(
        checkpoint,
        {
            "interrupt_id": pending.id,
            # `pending_approval_requests` synthesizes approval-0 here (no AI
            # message carries the tool call in this minimal graph).
            "decisions": [{"tool_call_id": "approval-0", "type": "approve"}],
        },
    )
    assert command == {"resume": {pending.id: {"decisions": [{"type": "approve"}]}}}

    out = await graph.ainvoke(Command(resume=command["resume"]), config)
    assert out["answer"] == "approve"
