"""Graph-level tests for `Agent.build`/`Agent.stream` (design review §6.2 gap 3).

`test_runtime.py` asserts middleware *lists*: it proves what was configured,
not what happens. These tests run the real graph against a
`ScriptedChatModel`, so the assertions are behavioural — a tool ran, a failure
came back as a message, the recursion fallback persisted something the next
turn can resume from. They exist to make the P2-3 unification of
`build_runnable` a refactor with a safety net instead of a leap of faith.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.run_spec import AgentSpec
from app.agents.runtime import RECURSION_LIMIT_MESSAGE, Agent, ResolvedAgent
from app.agents.toolset import PreparedToolset, Toolset
from tests.agents.scripted_model import ScriptedChatModel


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def explode() -> str:
    """Always fails."""
    raise RuntimeError("upstream MCP transport died")


class LiveToolsetStub:
    """Stands in for the toolset `Toolset.open` binds to a live MCP session."""

    def __init__(self, tools: list):
        self.all = tools


def _prepared(tools: list) -> PreparedToolset:
    prepared = PreparedToolset(
        client=None,
        server_names=[],
        tool_settings={},
        server_id_by_name={},
        interrupt_on={},
        apply_ui=False,
    )
    # `Agent._setup` replaces `resolved.live` with whatever `Toolset.open`
    # yields, so the tools a test wants have to travel on the prepared spec.
    prepared.tools_for_test = tools
    return prepared


def _spec(instructions: str = "You are a test agent") -> AgentSpec:
    spec = MagicMock(spec=AgentSpec)
    spec.instructions = instructions
    spec.name = "Tester"
    spec.description = "a test agent"
    spec.sandbox = None
    return spec


def _thread(thread_id: str = "thread-1") -> MagicMock:
    thread = MagicMock()
    thread.id = thread_id
    thread.user_id = "user-1"
    thread.agent_id = "agent-1"
    thread.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return thread


def build_agent(
    *,
    script: list,
    tools: list | None = None,
    middleware: list | None = None,
    interrupt_on: dict | None = None,
    instructions: str = "You are a test agent",
) -> tuple[Agent, ScriptedChatModel]:
    """An `Agent` whose graph is real and whose model is scripted."""
    from app.agents.runtime import build_parent_middleware

    prepared = _prepared(tools or [])
    if interrupt_on:
        prepared.interrupt_on = interrupt_on
    resolved = ResolvedAgent(config=_spec(instructions), prepared=prepared)
    resolved.live = LiveToolsetStub(tools or [])
    model = ScriptedChatModel(script=script)
    agent = Agent(
        thread=_thread(),
        agent=resolved,
        model=model,
        middleware=middleware
        if middleware is not None
        else build_parent_middleware(datetime(2026, 1, 1, tzinfo=UTC), prepared),
        callbacks=[],
        subagents=[],
        provider="openai",
    )
    return agent, model


@pytest.fixture
def in_memory_runtime():
    """Run `Agent.stream` against an in-memory checkpointer and no MCP sessions."""
    saver = InMemorySaver()

    @asynccontextmanager
    async def fake_checkpointer():
        yield saver

    @asynccontextmanager
    async def fake_open(prepared):
        yield LiveToolsetStub(prepared.tools_for_test)

    with (
        patch("app.agents.runtime.get_checkpointer", fake_checkpointer),
        patch.object(Toolset, "open", fake_open),
    ):
        yield saver


async def collect(agent: Agent, text: str = "hello", **kwargs) -> list[str]:
    """Run a turn; each yielded protocol event, JSON-encoded, so tests can
    grep the stream for the text that reached the wire."""
    chunks = []
    async for event in agent.stream(
        agent_input={"messages": [{"type": "human", "content": text}]}, **kwargs
    ):
        chunks.append(json.dumps(event, default=str))
    return chunks


def system_text(model: ScriptedChatModel, call: int = 0) -> str:
    """The system prompt as the model saw it, flattened across content blocks."""
    content = model.calls[call][0].content
    if isinstance(content, str):
        return content
    return "\n\n".join(
        block["text"] for block in content if block.get("type") == "text"
    )


def final_messages(saver: InMemorySaver, thread_id: str = "thread-1") -> list:
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = saver.get(config)
    return checkpoint["channel_values"]["messages"] if checkpoint else []


@pytest.mark.asyncio
async def test_stream_runs_the_graph_and_emits_the_model_answer(in_memory_runtime):
    """The baseline: a scripted turn reaches the SSE stream and the checkpoint."""
    agent, model = build_agent(script=["42 is the answer"])

    chunks = await collect(agent, "what is the answer?")

    assert any("42 is the answer" in chunk for chunk in chunks)
    assert [m.content for m in final_messages(in_memory_runtime)][-1] == (
        "42 is the answer"
    )
    # The instructions reached the model as its system prompt.
    assert model.calls[0][0].type == "system"
    assert system_text(model).startswith("You are a test agent")


@pytest.mark.asyncio
async def test_stream_executes_a_tool_and_feeds_the_result_back(in_memory_runtime):
    """A tool call round-trips: the tool runs, its ToolMessage is in the next
    model call, and the second turn's text is what the user sees."""
    agent, model = build_agent(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "call-1"}],
            ),
            "the sum is 5",
        ],
        tools=[add],
    )

    chunks = await collect(agent, "add 2 and 3")

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
    agent, model = build_agent(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "explode", "args": {}, "id": "call-1"}],
            ),
            "that tool is down, sorry",
        ],
        tools=[explode],
    )

    chunks = await collect(agent, "please explode")

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
    monkeypatch.setattr("app.agents.settings.agent_settings.recursion_limit", 3)
    looping = AIMessage(
        content="",
        tool_calls=[{"name": "add", "args": {"a": 1, "b": 1}, "id": "call-x"}],
    )
    agent, _ = build_agent(script=[looping] * 6, tools=[add])

    chunks = await collect(agent, "loop forever")

    # The SSE payload is JSON-encoded, so match the unescaped prefix.
    assert any("I reached my step limit" in chunk for chunk in chunks)
    assert final_messages(in_memory_runtime)[-1].content == RECURSION_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_hitl_interrupts_before_an_approval_gated_tool_runs(in_memory_runtime):
    """An approval-gated tool must not execute before the interrupt: the stream
    ends on the interrupt and the tool's result never reaches the model."""
    agent, model = build_agent(
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

    await collect(agent, "add 2 and 3")

    # One model call only — the graph stopped at the approval gate.
    assert len(model.calls) == 1
    state = in_memory_runtime.get_tuple({"configurable": {"thread_id": "thread-1"}})
    assert state is not None
    assert not [m for m in final_messages(in_memory_runtime) if m.type == "tool"]


@pytest.mark.asyncio
async def test_model_failure_ends_the_turn_visibly_and_still_persists_the_sandbox(
    in_memory_runtime,
):
    """A model that keeps failing must not crash the run: ModelRetryMiddleware
    exhausts its retries and persists the failure as an AIMessage. `stream`'s
    `finally` is the only turn-end hook a sandbox gets, so the snapshot has to
    run on that path too."""
    agent, model = build_agent(script=[])  # exhausted script -> every call raises

    with patch.object(Agent, "_persist_sandbox") as persist:
        await collect(agent, "boom")

    persist.assert_called_once()
    assert len(model.calls) > 1, "the failure was not retried"
    last = final_messages(in_memory_runtime)[-1]
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
    agent, _ = build_agent(script=["ignored"])
    config = {"configurable": {"thread_id": "thread-1"}}

    # Seed a previous turn's structured response.
    with patch("app.agents.runtime.get_checkpointer"):
        pass
    graph = agent._build_agent(in_memory_runtime, output_schema=schema)
    await graph.aupdate_state(config, {"structured_response": {"answer": 1}})

    agent2, _ = build_agent(script=["fresh"])
    with patch.object(Agent, "_build_agent", return_value=graph):
        await collect(agent2, "again", output_schema=schema)

    state = await graph.aget_state(config)
    assert state.values.get("structured_response") is None


# --- The sandbox path -------------------------------------------------------
#
# These pin what a sandbox-bound agent is actually offered today, which is the
# contract P2-3 has to preserve when `build_runnable` stops dispatching to
# `create_deep_agent`. `test_harness_parity.py` proves the two assemblies match
# instruction-for-instruction; these prove the result runs.


def build_sandbox_agent(*, script: list, tools: list | None = None):
    """An `Agent` with a sandbox binding, i.e. the deepagents-harness path."""
    from app.agents.runtime import ResolvedSandbox, build_parent_middleware

    prepared = _prepared(tools or [])
    resolved = ResolvedAgent(config=_spec(), prepared=prepared)
    resolved.sandbox = ResolvedSandbox(provider=MagicMock(), tools=None)
    resolved.live = LiveToolsetStub(tools or [])
    model = ScriptedChatModel(script=script)
    agent = Agent(
        thread=_thread("thread-sandbox"),
        agent=resolved,
        model=model,
        middleware=build_parent_middleware(datetime(2026, 1, 1, tzinfo=UTC), prepared),
        callbacks=[],
        subagents=[],
        provider="openai",
    )
    return agent, model


@pytest.mark.asyncio
async def test_sandbox_agent_is_offered_the_full_harness_toolset(in_memory_runtime):
    """A sandbox agent gets deepagents' harness: todo, filesystem, `execute`,
    the `task` tool (from the auto-added general-purpose subagent) and our own
    sandbox lifecycle tools — plus the harness prompt appended to the agent's
    instructions."""
    agent, model = build_sandbox_agent(script=["done"], tools=[add])

    await collect(agent, "hello")

    names = {t.name for t in model.bound_tools}
    assert {"add", "create_sandbox", "connect_sandbox"} <= names
    assert {"write_todos", "ls", "read_file", "write_file", "execute"} <= names
    assert "task" in names
    system = system_text(model)
    assert system.startswith("You are a test agent")
    assert "You are a deep agent" in system


@pytest.mark.asyncio
async def test_sandbox_agent_persists_the_sandbox_at_turn_end(in_memory_runtime):
    """The snapshot hook runs once per turn, on the way out of `stream`."""
    agent, _ = build_sandbox_agent(script=["done"])

    with patch.object(Agent, "_persist_sandbox") as persist:
        await collect(agent, "hello")

    persist.assert_called_once()


@pytest.mark.asyncio
async def test_plain_agent_is_offered_only_its_own_tools(in_memory_runtime):
    """The counterpart to the harness test: without a sandbox the agent gets
    no filesystem, no todos and no `task` tool, and its instructions are the
    whole system prompt."""
    agent, model = build_agent(script=["done"], tools=[add])

    await collect(agent, "hello")

    assert {t.name for t in model.bound_tools} == {"add"}
    system = system_text(model)
    assert system.startswith("You are a test agent")
    assert "You are a deep agent" not in system


# --- Regeneration and input resolution --------------------------------------


@pytest.mark.asyncio
async def test_regeneration_forks_from_before_the_last_user_message(in_memory_runtime):
    """Regenerating replays the last turn: it forks from the checkpoint the
    user's message was applied to, so the thread ends with one answer, not two
    questions."""
    agent, _ = build_agent(script=["first answer"])
    await collect(agent, "question one")
    agent, _ = build_agent(script=["second answer"])
    await collect(agent, "question two")

    agent, _ = build_agent(script=["a different second answer"])
    await collect(agent, "question two", trigger="regenerate-message")

    kinds = [(m.type, m.content) for m in final_messages(in_memory_runtime)]
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
    agent, _ = build_agent(script=["first answer"])
    await collect(agent, "only question")

    agent, _ = build_agent(script=["better answer"])
    await collect(agent, "only question", trigger="regenerate-message")

    assert [(m.type, m.content) for m in final_messages(in_memory_runtime)] == [
        ("human", "only question"),
        ("ai", "better answer"),
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
    from app.exceptions import DomainValidationError

    agent, _ = build_agent(script=["never reached"])

    with pytest.raises(DomainValidationError, match="Invalid run input"):
        async for _ in agent.stream(agent_input={"messages": messages}):
            pass


@pytest.mark.asyncio
async def test_subagent_wiring_keeps_the_caller_prompt_ahead_of_the_task_block():
    """A plain agent with subagents assembles its prompt caller-fragments-first.
    `SubAgentMiddleware` sitting on the wrong side of the caller's stack moves
    the `task` block ahead of them — a silent prompt rewrite on every
    non-sandbox agent that has subagents, whose prompts are frozen at creation.
    """
    from deepagents.middleware.subagents import CompiledSubAgent

    from app.agents.current_date import CurrentDateMiddleware
    from app.agents.runtime import build_runnable

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

    system = system_text(model)
    assert system.index("Current date:") < system.index("`task` (subagent spawner)")
