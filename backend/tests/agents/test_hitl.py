"""HITL checkpoint reading + resume-command canonicalization (`app/agents/hitl.py`)."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.hitl import (
    build_resume_command,
    is_addressed_resume,
    load_interrupt_scope,
    load_interrupt_scopes,
    pending_approval_requests,
    pending_interrupt,
    pending_interrupts,
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
    assert out == (INTERRUPT_ID, {"a": 1}, "t")


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


@pytest.mark.parametrize(
    "decisions",
    [
        42,  # not a list at all — iterating would TypeError
        {"call_1": "approve"},  # a dict is not the list shape
        "approve",  # nor is a bare string
        [{"tool_call_id": ["call_1"], "type": "approve"}],  # unhashable id
        [{"tool_call_id": 7, "type": "approve"}],  # non-string id
    ],
)
def test_malformed_decisions_are_a_400_not_a_typeerror(decisions):
    """cubic P2: client payloads are the client's fault — every malformed
    shape must surface as DomainValidationError, never a 500."""
    resume = {"interrupt_id": INTERRUPT_ID, "decisions": decisions}
    with pytest.raises(DomainValidationError):
        build_resume_command(_two_call_checkpoint(), resume)


@pytest.mark.parametrize("decisions", [{}, 0, "", False, None])
def test_falsy_non_list_decisions_hit_the_type_check(decisions):
    """cubic P3 (round 2): `or []` used to coerce falsy non-lists into "no
    decisions supplied", yielding the misleading coverage error instead of
    the type error."""
    resume = {"interrupt_id": INTERRUPT_ID, "decisions": decisions}
    with pytest.raises(DomainValidationError, match="must be a list"):
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


# ---------------------------------------------------------------------------
# Subagent approvals — the interrupt is on the root, the tool call is not
# ---------------------------------------------------------------------------


def test_pending_approval_requests_reads_tool_calls_from_the_scope():
    """A subagent's interrupt bubbles to the root, whose last AI message only
    carries the `task` call; the gated call is in the subagent's checkpoint."""
    root = _checkpoint(
        {"action_requests": [{"name": "send_email", "args": {"to": "a@b.c"}}]},
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_task",
                        "name": "task",
                        "args": {"description": "mail them", "subagent_type": "w"},
                    }
                ],
            )
        ],
    )
    sub = _checkpoint(
        None,
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "sub_call", "name": "send_email", "args": {"to": "a@b.c"}}
                ],
            )
        ],
    )
    assert pending_approval_requests(root)[0]["tool_call_id"] == "approval-0"
    assert pending_approval_requests(root, sub)[0]["tool_call_id"] == "sub_call"
    command = build_resume_command(
        root,
        {
            "interrupt_id": INTERRUPT_ID,
            "decisions": [{"tool_call_id": "sub_call", "type": "reject"}],
        },
        sub,
    )
    assert command == {"resume": {INTERRUPT_ID: {"decisions": [{"type": "reject"}]}}}


class _Checkpointer:
    """`aget_tuple` over a dict keyed by checkpoint namespace."""

    def __init__(self, by_ns):
        self.by_ns = by_ns

    async def aget_tuple(self, config):
        return self.by_ns.get(config["configurable"].get("checkpoint_ns", ""))


async def test_load_interrupt_scope_stays_at_the_root_for_a_parent_approval():
    root = _two_call_checkpoint()
    scope = await load_interrupt_scope(_Checkpointer({"": root}), "t")
    assert scope is not None
    assert scope.namespace == ""
    assert scope.namespace_path == []
    assert scope.checkpoint is root
    assert scope.subagent_call is None
    assert scope.subagent_type is None
    assert scope.interrupt.id == INTERRUPT_ID
    assert scope.interrupt.task_id == "task-1"


async def test_load_interrupt_scope_is_none_when_nothing_pends():
    assert (
        await load_interrupt_scope(_Checkpointer({"": _checkpoint(None, [])}), "t")
        is None
    )
    assert await load_interrupt_scope(_Checkpointer({}), "t") is None


async def test_load_interrupt_scope_follows_the_task_into_the_subagent():
    """The root pending write's task is the parent's `tools` task; the subagent
    checkpointed under `tools:<that id>` pends on the same interrupt."""
    value = {"action_requests": [{"name": "send_email", "args": {}}]}
    task_call = {
        "id": "call_task",
        "name": "task",
        "args": {"description": "mail them", "subagent_type": "mailer"},
    }
    other_call = {
        "id": "call_task_2",
        "name": "task",
        "args": {"description": "something else", "subagent_type": "other"},
    }
    root = _checkpoint(
        value, [AIMessage(content="", tool_calls=[other_call, task_call])]
    )
    sub = _checkpoint(
        value,
        [
            HumanMessage(content="mail them"),
            AIMessage(
                content="",
                tool_calls=[{"id": "sub_call", "name": "send_email", "args": {}}],
            ),
        ],
    )
    sub.pending_writes[0] = ("hitl-task", "__interrupt__", sub.pending_writes[0][2])
    unrelated = _checkpoint(value, [], interrupt_id="cd" * 16)
    checkpointer = _Checkpointer(
        {"": root, "tools:task-1": sub, "tools:task-1|tools:hitl-task": unrelated}
    )

    scope = await load_interrupt_scope(checkpointer, "t")
    assert scope is not None
    assert scope.namespace == "tools:task-1"  # stops: the deeper one is another id
    assert scope.namespace_path == ["tools:task-1"]
    assert scope.checkpoint is sub
    assert scope.root is root
    # Told apart from the parallel sibling by the subagent's seed message.
    assert scope.subagent_call is not None
    assert scope.subagent_call["id"] == task_call["id"]
    assert scope.subagent_type == "mailer"
    assert pending_approval_requests(scope.root, scope.checkpoint) == [
        {"tool_call_id": "sub_call", "tool_name": "send_email", "input": {}}
    ]


async def test_parallel_subagent_interrupts_are_addressed_by_id():
    """Two subagents paused in one superstep: two root pending writes. An
    addressed resume picks its own interrupt and follows *its* task, not the
    first one's."""
    from types import SimpleNamespace

    id_a, id_b = "aa" * 16, "bb" * 16
    calls = [
        {
            "id": "call_a",
            "name": "task",
            "args": {"description": "A", "subagent_type": "a"},
        },
        {
            "id": "call_b",
            "name": "task",
            "args": {"description": "B", "subagent_type": "b"},
        },
    ]
    root = SimpleNamespace(
        pending_writes=[
            (
                "task-a",
                "__interrupt__",
                [SimpleNamespace(value={"action_requests": []}, id=id_a)],
            ),
            (
                "task-b",
                "__interrupt__",
                [SimpleNamespace(value={"action_requests": []}, id=id_b)],
            ),
        ],
        checkpoint={
            "channel_values": {"messages": [AIMessage(content="", tool_calls=calls)]}
        },
    )
    sub_a = _checkpoint({"action_requests": []}, [HumanMessage("A")], interrupt_id=id_a)
    sub_b = _checkpoint({"action_requests": []}, [HumanMessage("B")], interrupt_id=id_b)
    checkpointer = _Checkpointer(
        {"": root, "tools:task-a": sub_a, "tools:task-b": sub_b}
    )

    assert [i.id for i in pending_interrupts(root)] == [id_a, id_b]
    assert pending_interrupt(root).id == id_a
    assert pending_interrupt(root, id_b).id == id_b
    assert pending_interrupt(root, "cd" * 16) is None

    scope_b = await load_interrupt_scope(checkpointer, "t", interrupt_id=id_b)
    assert scope_b is not None
    assert scope_b.namespace == "tools:task-b"
    assert scope_b.subagent_type == "b"
    scopes = await load_interrupt_scopes(checkpointer, "t")
    assert [(s.interrupt.id, s.namespace, s.subagent_type) for s in scopes] == [
        (id_a, "tools:task-a", "a"),
        (id_b, "tools:task-b", "b"),
    ]
    with pytest.raises(StaleApprovalError):
        build_resume_command(
            root, {"interrupt_id": "cd" * 16, "decisions": []}, scope_b.checkpoint
        )


async def test_load_interrupt_scope_descent_is_bounded():
    """A checkpointer that answers every namespace with the same paused
    checkpoint (a test double, a misbehaving store) must not loop forever."""
    from app.agents.hitl import MAX_SUBAGENT_DEPTH

    class _Everywhere:
        async def aget_tuple(self, config):
            return _two_call_checkpoint()

    scope = await load_interrupt_scope(_Everywhere(), "t")
    assert scope is not None
    assert scope.namespace.count("tools:") == MAX_SUBAGENT_DEPTH


async def test_load_interrupt_scope_end_to_end_through_a_gated_subagent():
    """The real thing: a supervisor delegates through deepagents' `task` to a
    subagent whose tool is gated by our middleware stack. The interrupt lands
    on the root checkpoint, the scope resolves to the subagent's namespace with
    the real tool_call_id, and the canonical resume finishes both agents."""
    from datetime import UTC, datetime

    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from app.agents.runtime import build_agent_middleware, build_runnable

    class _ToolFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    @tool
    def send_email(to: str) -> str:
        """Send an email."""
        return f"sent to {to}"

    now = datetime.now(UTC)
    worker = CompiledSubAgent(
        name="mailer",
        description="mailer: sends mail",
        runnable=build_runnable(
            model=_ToolFake(
                messages=iter(
                    [
                        AIMessage(
                            content="",
                            id="sub-ai-1",
                            tool_calls=[
                                {
                                    "id": "sub_call",
                                    "name": "send_email",
                                    "args": {"to": "a@b.c"},
                                }
                            ],
                        ),
                        AIMessage(content="mail sent", id="sub-ai-2"),
                    ]
                )
            ),
            tools=[send_email],
            system_prompt="mailer",
            base_middleware=build_agent_middleware(
                now, recursion_limit=25, interrupt_on={"send_email": True}
            ),
        ),
    )
    saver = InMemorySaver()
    parent = build_runnable(
        model=_ToolFake(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        id="root-ai-1",
                        tool_calls=[
                            {
                                "id": "call_task",
                                "name": "task",
                                "args": {
                                    "description": "mail them",
                                    "subagent_type": "mailer",
                                },
                            }
                        ],
                    ),
                    AIMessage(content="done", id="root-ai-2"),
                ]
            )
        ),
        tools=[],
        system_prompt="supervisor",
        base_middleware=build_agent_middleware(
            now, recursion_limit=50, interrupt_on={}
        ),
        subagents=[worker],
        checkpointer=saver,
    )
    config = {"configurable": {"thread_id": "t-sub-hitl"}}
    await parent.ainvoke({"messages": [HumanMessage("go")]}, config)  # pauses

    scope = await load_interrupt_scope(saver, "t-sub-hitl")
    assert scope is not None
    assert scope.namespace.startswith("tools:")
    assert scope.subagent_type == "mailer"
    assert scope.interrupt.id is not None and len(scope.interrupt.id) == 32
    requests = pending_approval_requests(scope.root, scope.checkpoint)
    assert requests == [
        {
            "tool_call_id": "sub_call",
            "tool_name": "send_email",
            "input": {"to": "a@b.c"},
        }
    ]

    command = build_resume_command(
        scope.root,
        {
            "interrupt_id": scope.interrupt.id,
            "decisions": [{"tool_call_id": "sub_call", "type": "approve"}],
        },
        scope.checkpoint,
    )
    out = await parent.ainvoke(Command(resume=command["resume"]), config)
    assert out["messages"][-1].content == "done"
    assert await load_interrupt_scope(saver, "t-sub-hitl") is None
    sub_state = await saver.aget_tuple(
        {"configurable": {"thread_id": "t-sub-hitl", "checkpoint_ns": scope.namespace}}
    )
    sub_messages = sub_state.checkpoint["channel_values"]["messages"]
    assert [m.type for m in sub_messages] == ["human", "ai", "tool", "ai"]
    assert sub_messages[2].content == "sent to a@b.c"
