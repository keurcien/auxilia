"""Graph-level tests for the runtime pipeline (design review §6.2 gap 3).

`test_agent.py` asserts middleware *lists*: it proves what was configured,
not what happens. These tests run the real graph against a
`ScriptedChatModel`, so the assertions are behavioural — a tool ran, a failure
came back as a message, the recursion fallback persisted something the next
turn can resume from. `collect` drives the stages exactly as the worker does:
`open_resources` → stamp → `assemble` → `run_turn`.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.run_spec import AgentSpec
from app.exceptions import DomainValidationError
from app.runtime.assemble import assemble
from app.runtime.checkpoints import get_checkpoint_state
from app.runtime.resolve import ResolvedAgent, ResolvedRun, ResolvedSandbox
from app.runtime.resources import open_resources
from app.runtime.toolset import PreparedToolset, Toolset
from app.runtime.turn import RECURSION_LIMIT_MESSAGE, TurnInput, run_turn
from tests.runtime.scripted_model import ScriptedChatModel
from tests.sandbox.stub_sandbox import StubSandbox


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def explode() -> str:
    """Always fails."""
    raise RuntimeError("upstream MCP transport died")


class LiveToolsetStub:
    """Stands in for the toolset `Toolset.open` binds to a live MCP connection."""

    def __init__(self, tools: list):
        self.all = tools


def _prepared(tools: list) -> PreparedToolset:
    prepared = PreparedToolset(
        connections={},
        tool_settings={},
        server_id_by_name={},
        interrupt_on={},
        apply_ui=False,
    )
    # `open_resources` binds whatever `Toolset.open` yields, so the tools a
    # test wants have to travel on the prepared spec.
    prepared.tools_for_test = tools
    return prepared


def _spec(instructions: str = "You are a test agent") -> AgentSpec:
    return AgentSpec(
        id=uuid4(),
        name="Tester",
        instructions=instructions,
        description="a test agent",
        mcp_servers=[],
        sandbox=None,
    )


def _thread(thread_id: str = "thread-1") -> MagicMock:
    thread = MagicMock()
    thread.id = thread_id
    thread.user_id = "user-1"
    thread.agent_id = "agent-1"
    thread.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    thread.sandbox_id = None
    # Explicit: an unset attribute on a MagicMock is a truthy mock, which
    # would read as "a different sandbox issued this id".
    thread.sandbox_source_id = None
    return thread


def build_agent(
    *,
    script: list,
    tools: list | None = None,
    interrupt_on: dict | None = None,
    instructions: str = "You are a test agent",
) -> tuple[ResolvedRun, ScriptedChatModel]:
    """A `ResolvedRun` whose graph is real and whose model is scripted."""
    prepared = _prepared(tools or [])
    if interrupt_on:
        prepared.interrupt_on = interrupt_on
    model = ScriptedChatModel(script=script)
    resolved = ResolvedRun(
        thread=_thread(),
        agent=ResolvedAgent(config=_spec(instructions), prepared=prepared),
        subagents=[],
        model=model,
        provider="openai",
    )
    resolved.remembered = []  # the sandbox stamps `collect` applied
    return resolved, model


@pytest.fixture
def in_memory_runtime():
    """Run the pipeline against an in-memory checkpointer and no MCP connections."""
    saver = InMemorySaver()

    @asynccontextmanager
    async def fake_checkpointer():
        yield saver

    @asynccontextmanager
    async def fake_open(prepared):
        yield LiveToolsetStub(prepared.tools_for_test)

    with (
        patch("app.runtime.resources.get_checkpointer", fake_checkpointer),
        patch.object(Toolset, "open", fake_open),
    ):
        yield saver


async def run(resolved: ResolvedRun, turn: TurnInput) -> list[dict]:
    """One turn, the way the worker runs it: open the resources, stamp the
    thread's sandbox, assemble the graph, drive it. Returns the raw events."""
    events = []
    async with open_resources(resolved) as live:
        if (stamp := live.sandbox_stamp(resolved.thread)) is not None:
            sandbox_id, source_id = stamp
            resolved.remembered.append(sandbox_id)
            resolved.thread.sandbox_id = sandbox_id
            resolved.thread.sandbox_source_id = source_id
        graph = assemble(resolved, live, output_schema=turn.output_schema)
        async for event in run_turn(graph, resolved, live, turn):
            events.append(event)
    return events


async def collect(
    resolved: ResolvedRun, text: str = "hello", **turn_kwargs
) -> list[str]:
    """Run a turn on `text`; each yielded protocol event, JSON-encoded, so
    tests can grep the stream for the text that reached the wire."""
    turn_kwargs.setdefault("input", {"messages": [{"type": "human", "content": text}]})
    events = await run(resolved, TurnInput(**turn_kwargs))
    return [json.dumps(event, default=str) for event in events]


def system_text(model: ScriptedChatModel, call: int = 0) -> str:
    """The system prompt as the model saw it, flattened across content blocks."""
    content = model.calls[call][0].content
    if isinstance(content, str):
        return content
    return "\n\n".join(
        block["text"] for block in content if block.get("type") == "text"
    )


async def final_messages(saver: InMemorySaver, thread_id: str = "thread-1") -> list:
    """The thread's messages as the graph sees them — through the state
    reader, since a `DeltaChannel` checkpoint does not carry them raw."""
    return (await get_checkpoint_state(saver, thread_id)).messages


@pytest.mark.asyncio
async def test_stream_runs_the_graph_and_emits_the_model_answer(in_memory_runtime):
    """The baseline: a scripted turn reaches the SSE stream and the checkpoint."""
    resolved, model = build_agent(script=["42 is the answer"])

    chunks = await collect(resolved, "what is the answer?")

    assert any("42 is the answer" in chunk for chunk in chunks)
    assert [m.content for m in await final_messages(in_memory_runtime)][-1] == (
        "42 is the answer"
    )
    # The instructions reached the model as its system prompt.
    assert model.calls[0][0].type == "system"
    assert system_text(model).startswith("You are a test agent")


@pytest.mark.asyncio
async def test_stream_executes_a_tool_and_feeds_the_result_back(in_memory_runtime):
    """A tool call round-trips: the tool runs, its ToolMessage is in the next
    model call, and the second turn's text is what the user sees."""
    resolved, model = build_agent(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "call-1"}],
            ),
            "the sum is 5",
        ],
        tools=[add],
    )

    chunks = await collect(resolved, "add 2 and 3")

    assert any("the sum is 5" in chunk for chunk in chunks)
    tool_messages = [m for m in model.calls[1] if m.type == "tool"]
    assert [m.content for m in tool_messages] == ["5"]


@pytest.mark.asyncio
async def test_tool_failure_comes_back_as_a_message_instead_of_killing_the_run(
    in_memory_runtime,
):
    """ToolErrorMiddleware's contract: an exception inside a tool must reach the
    model as an error ToolMessage. Without it langgraph re-raises and one dead
    MCP transport ends the whole run."""
    resolved, model = build_agent(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "explode", "args": {}, "id": "call-1"}],
            ),
            "that tool is down, sorry",
        ],
        tools=[explode],
    )

    chunks = await collect(resolved, "please explode")

    assert any("that tool is down" in chunk for chunk in chunks)
    tool_messages = [m for m in model.calls[1] if m.type == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"


@pytest.mark.asyncio
async def test_recursion_limit_persists_a_resumable_synthetic_message(
    in_memory_runtime, monkeypatch
):
    """When the graph blows its recursion limit the run must end visibly: a
    synthetic AI message is written to the checkpoint (so the next turn resumes)
    and streamed to the client (so the UI stops spinning)."""
    monkeypatch.setattr("app.runtime.settings.agent_settings.recursion_limit", 3)
    looping = AIMessage(
        content="",
        tool_calls=[{"name": "add", "args": {"a": 1, "b": 1}, "id": "call-x"}],
    )
    resolved, _ = build_agent(script=[looping] * 6, tools=[add])

    chunks = await collect(resolved, "loop forever")

    # The SSE payload is JSON-encoded, so match the unescaped prefix.
    assert any("I reached my step limit" in chunk for chunk in chunks)
    assert (await final_messages(in_memory_runtime))[
        -1
    ].content == RECURSION_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_hitl_interrupts_before_an_approval_gated_tool_runs(in_memory_runtime):
    """An approval-gated tool must not execute before the interrupt: the stream
    ends on the interrupt and the tool's result never reaches the model."""
    resolved, model = build_agent(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "call-1"}],
            ),
            "unreachable",
        ],
        tools=[add],
        interrupt_on={"add": True},
    )

    await collect(resolved, "add 2 and 3")

    # One model call only — the graph stopped at the approval gate.
    assert len(model.calls) == 1
    state = in_memory_runtime.get_tuple({"configurable": {"thread_id": "thread-1"}})
    assert state is not None
    assert not [m for m in await final_messages(in_memory_runtime) if m.type == "tool"]


@pytest.mark.asyncio
async def test_model_failure_ends_the_turn_visibly_and_still_persists_the_sandbox(
    in_memory_runtime,
):
    """A model that keeps failing must not crash the run: ModelRetryMiddleware
    exhausts its retries and persists the failure as an AIMessage. Leaving
    `open_resources` is the only turn-end hook a sandbox gets, so the snapshot
    has to run on that path too."""
    resolved, model = build_agent(script=[])  # exhausted script -> every call raises

    with patch("app.runtime.resources._persist_sandbox", new=AsyncMock()) as persist:
        await collect(resolved, "boom")

    persist.assert_awaited_once()
    assert len(model.calls) > 1, "the failure was not retried"
    last = (await final_messages(in_memory_runtime))[-1]
    assert last.type == "ai"
    assert "Model call failed" in last.content


@pytest.mark.asyncio
async def test_stale_structured_response_is_cleared_before_a_new_run(in_memory_runtime):
    """`structured_response` is a persistent channel: a turn that never reaches
    its formatting step must not read back the previous turn's object."""
    schema = {
        "title": "answer",
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }
    config = {"configurable": {"thread_id": "thread-1"}}
    resolved, _ = build_agent(script=["fresh"])
    turn = TurnInput(
        input={"messages": [{"type": "human", "content": "again"}]},
        output_schema=schema,
    )

    async with open_resources(resolved) as live:
        graph = assemble(resolved, live, output_schema=schema)
        # Seed a previous turn's structured response, then run a new turn on
        # the same graph.
        await graph.aupdate_state(config, {"structured_response": {"answer": 1}})
        async for _ in run_turn(graph, resolved, live, turn):
            pass
        state = await graph.aget_state(config)

    assert state.values.get("structured_response") is None


# --- The sandbox path -------------------------------------------------------
#
# These pin what a sandbox-bound agent is actually offered today, which is the
# contract P2-3 has to preserve when `build_runnable` stops dispatching to
# `create_deep_agent`. `test_harness_parity.py` proves the two assemblies match
# instruction-for-instruction; these prove the result runs.


def build_sandbox_agent(
    *, script: list, tools: list | None = None, skills=(), sandbox_id=None
):
    """A `ResolvedRun` with a sandbox binding, i.e. the deepagents-harness path.

    The provider is a fake whose `create`/`connect` hand out one `StubSandbox`
    (returned third); `collect` applies the thread stamp the worker would
    write, recording it in `resolved.remembered`.
    """
    prepared = _prepared(tools or [])
    sandbox = StubSandbox("sbx-live")
    provider = MagicMock()
    provider.create.return_value = sandbox
    provider.connect.return_value = sandbox
    agent = ResolvedAgent(config=_spec(), prepared=prepared)
    agent.sandbox = ResolvedSandbox(provider=provider, tools=None)
    model = ScriptedChatModel(script=script)
    thread = _thread("thread-sandbox")
    thread.sandbox_id = sandbox_id
    resolved = ResolvedRun(
        thread=thread,
        agent=agent,
        subagents=[],
        model=model,
        provider="openai",
        skills=list(skills),
    )
    resolved.remembered = []
    return resolved, model, sandbox


@pytest.mark.asyncio
async def test_sandbox_agent_is_offered_the_full_harness_toolset(in_memory_runtime):
    """A sandbox agent gets deepagents' harness: todo, filesystem, `execute`
    and the `task` tool (from the auto-added general-purpose subagent) — and
    no lifecycle tools: the runtime opened the sandbox before the graph ran —
    plus the harness prompt appended to the agent's instructions."""
    resolved, model, _ = build_sandbox_agent(script=["done"], tools=[add])

    await collect(resolved, "hello")

    names = {t.name for t in model.bound_tools}
    assert "add" in names
    assert not {"create_sandbox", "connect_sandbox"} & names
    assert {"write_todos", "ls", "read_file", "write_file", "execute"} <= names
    assert "task" in names
    system = system_text(model)
    assert system.startswith("You are a test agent")
    assert "write_todos" in system  # the todo middleware's prompt fragment


@pytest.mark.asyncio
async def test_sandbox_agent_persists_the_sandbox_at_turn_end(in_memory_runtime):
    """The snapshot hook runs once per turn, on the way out of
    `open_resources`, on the sandbox the runtime opened."""
    resolved, _, sandbox = build_sandbox_agent(script=["done"])

    await collect(resolved, "hello")

    assert sandbox.persisted == 1


@pytest.mark.asyncio
async def test_sandbox_is_created_once_and_reconnected_after(in_memory_runtime):
    """First run of a thread: no sandbox id, so one is created and stamped on
    the thread. Later runs reconnect to that id and stamp nothing."""
    resolved, _, _ = build_sandbox_agent(script=["done", "done"])
    provider = resolved.agent.sandbox.provider

    await collect(resolved, "hello")
    assert provider.create.call_count == 1
    assert resolved.remembered == ["sbx-live"]

    await collect(resolved, "again")
    provider.connect.assert_called_once_with("sbx-live")
    assert provider.create.call_count == 1
    assert resolved.remembered == ["sbx-live"]


@pytest.mark.asyncio
async def test_replaced_sandbox_tells_the_model_once(in_memory_runtime):
    """A gone sandbox is replaced, the thread re-stamped, and one host notice
    lands in the checkpoint ahead of the user's message — so the model knows
    its earlier files are gone. The notice is a `HumanMessage` tagged so the
    chat renders it as an event, not as the user."""
    from app.sandbox.provider import SandboxGoneError

    resolved, model, _ = build_sandbox_agent(script=["done"], sandbox_id="sbx-old")
    resolved.agent.sandbox.provider.connect.side_effect = SandboxGoneError("expired")

    await collect(resolved, "hello")

    assert resolved.remembered == ["sbx-live"]
    state = await get_checkpoint_state(in_memory_runtime, "thread-sandbox")
    [notice, question, _answer] = state.messages
    assert notice.name == "host"
    assert notice.additional_kwargs["host_notice"] == "sandbox_replaced"
    assert "new, empty sandbox" in notice.content
    assert question.content == "hello"
    # The model saw it too, as a user-role turn ahead of the question.
    assert "sandbox" in model.calls[0][1].content


@pytest.mark.asyncio
async def test_plain_agent_is_offered_only_its_own_tools(in_memory_runtime):
    """The counterpart to the harness test: without a sandbox the agent gets
    no filesystem, no todos and no `task` tool, and its instructions are the
    whole system prompt."""
    resolved, model = build_agent(script=["done"], tools=[add])

    await collect(resolved, "hello")

    assert {t.name for t in model.bound_tools} == {"add"}
    system = system_text(model)
    assert system.startswith("You are a test agent")
    assert "write_todos" not in system


# --- Regeneration and input resolution --------------------------------------


@pytest.mark.asyncio
async def test_regeneration_forks_from_before_the_last_user_message(in_memory_runtime):
    """Regenerating replays the last turn: it forks from the checkpoint the
    user's message was applied to, so the thread ends with one answer, not two
    questions."""
    resolved, _ = build_agent(script=["first answer"])
    await collect(resolved, "question one")
    resolved, _ = build_agent(script=["second answer"])
    await collect(resolved, "question two")

    resolved, _ = build_agent(script=["a different second answer"])
    await collect(resolved, "question two", trigger="regenerate-message")

    kinds = [(m.type, m.content) for m in await final_messages(in_memory_runtime)]
    assert kinds == [
        ("human", "question one"),
        ("ai", "first answer"),
        ("human", "question two"),
        ("ai", "a different second answer"),
    ]


@pytest.mark.asyncio
async def test_regeneration_on_a_first_turn_has_something_to_fork_from(
    in_memory_runtime,
):
    """The very first turn's input checkpoint is the empty state; regenerating
    it must replace the answer rather than fail or append."""
    resolved, _ = build_agent(script=["first answer"])
    await collect(resolved, "only question")

    resolved, _ = build_agent(script=["better answer"])
    await collect(resolved, "only question", trigger="regenerate-message")

    assert [(m.type, m.content) for m in await final_messages(in_memory_runtime)] == [
        ("human", "only question"),
        ("ai", "better answer"),
    ]


@pytest.mark.asyncio
async def test_regeneration_without_input_replays_the_turns_message_under_its_id(
    in_memory_runtime,
):
    """The page regenerates with `submit(null, …)` — no input, so it echoes
    nothing optimistically. The server re-sends the turn's message itself,
    under its original id, so the first snapshot the page receives keeps the
    question in place and only the answer changes."""
    resolved, _ = build_agent(script=["first answer"])
    await collect(resolved, "question one")
    resolved, _ = build_agent(script=["second answer"])
    await run(
        resolved,
        TurnInput(
            input={
                "messages": [{"type": "human", "content": "question two", "id": "h2"}]
            }
        ),
    )

    resolved, _ = build_agent(script=["a different second answer"])
    events = await run(resolved, TurnInput(trigger="regenerate-message"))

    final = await final_messages(in_memory_runtime)
    assert [(m.type, m.content) for m in final] == [
        ("human", "question one"),
        ("ai", "first answer"),
        ("human", "question two"),
        ("ai", "a different second answer"),
    ]
    assert final[2].id == "h2"
    first_snapshot = next(
        e
        for e in events
        if e["method"] == "values" and "messages" in e["params"]["data"]
    )
    assert [m["id"] for m in first_snapshot["params"]["data"]["messages"]][-1] == "h2"


@pytest.mark.asyncio
async def test_regeneration_with_nothing_to_redo_is_rejected(in_memory_runtime):
    resolved, _ = build_agent(script=["hello"])
    with pytest.raises(DomainValidationError):
        await run(resolved, TurnInput(trigger="regenerate-message"))


@pytest.mark.asyncio
async def test_regenerating_twice_keeps_one_copy_of_the_question(in_memory_runtime):
    """Regeneration forks from the *end of the previous turn*, not from the
    turn's input checkpoint. Under `DeepAgentState` the latter is a trap:
    langgraph re-persists the input checkpoint's pending write on the fork it
    creates, and the `DeltaChannel` replay then shows the question twice — to
    every reader and, worse, to the model on the next turn."""
    resolved, _ = build_agent(script=["first answer"])
    await collect(resolved, "question one")
    resolved, _ = build_agent(script=["second answer"])
    await collect(resolved, "question two")
    for answer in ("take two", "take three"):
        resolved, _ = build_agent(script=[answer])
        await collect(resolved, "question two", trigger="regenerate-message")

    resolved, model = build_agent(script=["third answer"])
    await collect(resolved, "question three")

    seen = [(m.type, m.content) for m in model.calls[0] if m.type != "system"]
    assert seen == [
        ("human", "question one"),
        ("ai", "first answer"),
        ("human", "question two"),
        ("ai", "take three"),
        ("human", "question three"),
    ]


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([{"type": "wizard", "content": "hi"}], id="unknown-role"),
        pytest.param([{"role": "user"}], id="missing-content"),
        # Not a message at all: `convert_to_messages` raises NotImplementedError
        # rather than ValueError for these, which would have been a 500.
        pytest.param([42], id="not-a-message"),
        pytest.param([None], id="null-message"),
        pytest.param([["nested"]], id="nested-list"),
        pytest.param("hi", id="messages-not-a-list"),
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_input_message_is_a_bad_request(in_memory_runtime, messages):
    """Run input is client-supplied. An unknown role used to be filed silently
    as a user turn; every malformed shape is a validation error now, whichever
    exception the converter picks for it."""
    resolved, _ = build_agent(script=["never reached"])

    with pytest.raises(DomainValidationError, match="Invalid run input"):
        await run(resolved, TurnInput(input={"messages": messages}))


@pytest.mark.asyncio
async def test_plain_agent_with_subagents_binds_task_and_keeps_caller_fragments():
    """A plain agent with subagents gets the `task` tool from the wired-in
    `SubAgentMiddleware` and still carries the caller's own prompt fragments.
    (deepagents 0.7's middleware injects no prompt fragment of its own, so its
    position relative to the caller's stack is no longer visible in the
    prompt; `test_plain_path_wires_subagents_after_the_caller_stack` pins the
    order on the middleware list instead.)"""
    from deepagents.middleware.subagents import CompiledSubAgent

    from app.runtime.assemble import build_runnable
    from app.runtime.middleware.current_date import CurrentDateMiddleware

    class _Stub:
        def with_config(self, config):
            return self

    model = ScriptedChatModel(script=["done"])
    graph = build_runnable(
        model=model,
        tools=[],
        system_prompt="You are a test agent",
        base_middleware=[CurrentDateMiddleware(datetime(2026, 1, 1, tzinfo=UTC))],
        subagents=[
            CompiledSubAgent(name="helper", description="helps", runnable=_Stub())
        ],
    )

    await graph.ainvoke({"messages": [{"role": "user", "content": "hi"}]})

    assert "task" in {t.name for t in model.bound_tools}
    assert "Current date:" in system_text(model)


async def test_a_rebound_sandbox_ignores_the_previous_provider_s_id(in_memory_runtime):
    """Review finding: the thread's `sandbox_id` was handed to whatever
    provider the agent is bound to *now*. After a rebinding that id belongs to
    the old provider, which cannot know it — the run failed instead of
    starting a fresh sandbox."""
    resolved, _model, _ = build_sandbox_agent(script=["done"], sandbox_id="sbx-old")
    # The id was issued by a sandbox the agent is no longer bound to.
    resolved.thread.sandbox_source_id = uuid4()
    resolved.agent.sandbox.row_id = uuid4()

    await collect(resolved, "hello")

    # Reconnect was never attempted with the foreign id.
    resolved.agent.sandbox.provider.connect.assert_not_called()
    assert resolved.remembered == ["sbx-live"]
