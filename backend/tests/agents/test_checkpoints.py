"""`get_checkpoint_state` rebuilds a `DeltaChannel` thread the way the graph does.

Every agent graph is compiled with `DeepAgentState`, so a checkpoint's raw
`channel_values` stop carrying `messages` between snapshots. These tests run
real graphs on an in-memory saver and check the reader against the graph's
own `aget_state`, on the root, on a subagent namespace, past a snapshot, on
a pre-migration thread, and on a thread that does not exist.
"""

import pytest
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.checkpoints import EMPTY_STATE, get_checkpoint_state
from tests.agents.scripted_model import ScriptedChatModel


@tool
def ping(n: int) -> str:
    """Ping."""
    return f"pong {n}"


def _tool_turns(turns: int, *, then: str = "done") -> list:
    """`turns` model turns that each call `ping`, then a final answer."""
    return [
        *(
            AIMessage(
                content="",
                tool_calls=[{"name": "ping", "args": {"n": i}, "id": f"c{i}"}],
            )
            for i in range(turns)
        ),
        then,
    ]


@pytest.mark.asyncio
async def test_reader_matches_the_graph_past_a_snapshot():
    """30 tool turns = 60+ `messages` updates: past one `_DeltaSnapshot` (every
    50th) and ending off-snapshot, where the raw checkpoint has no `messages`."""
    saver = InMemorySaver()
    graph = create_agent(
        model=ScriptedChatModel(script=_tool_turns(30)),
        tools=[ping],
        checkpointer=saver,
        state_schema=DeepAgentState,
    )
    config = {"configurable": {"thread_id": "t-delta"}}
    await graph.ainvoke({"messages": [("user", "hi")]}, config, recursion_limit=200)

    raw = await saver.aget_tuple(config)
    assert "messages" not in raw.checkpoint["channel_values"]

    state = await get_checkpoint_state(saver, "t-delta")
    truth = (await graph.aget_state(config)).values["messages"]
    assert len(truth) == 62  # human + 30 × (ai, tool) + final ai
    assert state.messages == truth  # whole messages, not just ids
    assert state.saved is not None
    assert state.saved.checkpoint["id"] == raw.checkpoint["id"]


@pytest.mark.asyncio
async def test_reader_reads_a_subagent_namespace():
    """A `task` subagent checkpoints under `tools:<pregel task id>`; the reader
    rebuilds its messages there, which the subagent graph itself cannot (it is
    compiled without a checkpointer, and langgraph only walks delta history
    through the compiled-in one)."""
    saver = InMemorySaver()
    sub = create_agent(
        model=ScriptedChatModel(script=_tool_turns(3, then="sub done")),
        tools=[ping],
        state_schema=DeepAgentState,
    )
    task_call = {
        "name": "task",
        "args": {"description": "go", "subagent_type": "helper"},
        "id": "t1",
    }
    graph = create_agent(
        model=ScriptedChatModel(
            script=[AIMessage(content="", tool_calls=[task_call]), "done"]
        ),
        tools=[ping],
        middleware=[
            SubAgentMiddleware(
                backend=StateBackend(),
                subagents=[
                    CompiledSubAgent(name="helper", description="h", runnable=sub)
                ],
            )
        ],
        checkpointer=saver,
        state_schema=DeepAgentState,
    )
    await graph.ainvoke(
        {"messages": [("user", "hi")]}, {"configurable": {"thread_id": "t-sub"}}
    )

    namespaces = {
        ct.config["configurable"].get("checkpoint_ns", "")
        async for ct in saver.alist({"configurable": {"thread_id": "t-sub"}})
    }
    (namespace,) = {ns for ns in namespaces if ns}
    assert namespace.startswith("tools:")

    state = await get_checkpoint_state(saver, "t-sub", namespace)
    assert state.messages[0].content == "go"  # the task description seeds it
    assert state.messages[-1].content == "sub done"
    assert len(state.messages) == 8  # seed + 3 × (ai, tool) + final ai


@pytest.mark.asyncio
async def test_reader_reads_a_pre_migration_thread():
    """A thread checkpointed with `add_messages` (a plain list under
    `channel_values["messages"]`) reads the same through the delta reader."""
    saver = InMemorySaver()
    legacy = create_agent(
        model=ScriptedChatModel(script=_tool_turns(2)), tools=[ping], checkpointer=saver
    )
    config = {"configurable": {"thread_id": "t-legacy"}}
    await legacy.ainvoke({"messages": [("user", "hi")]}, config)

    raw = await saver.aget_tuple(config)
    assert isinstance(raw.checkpoint["channel_values"]["messages"], list)

    state = await get_checkpoint_state(saver, "t-legacy")
    truth = (await legacy.aget_state(config)).values["messages"]
    assert state.messages == truth and len(truth) == 6


@pytest.mark.asyncio
async def test_reader_surfaces_todos_and_structured_response():
    """The other channels the readers project, from the middleware that
    writes them."""
    saver = InMemorySaver()
    todos = [{"content": "look", "status": "pending"}]
    graph = create_agent(
        model=ScriptedChatModel(
            script=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "write_todos", "args": {"todos": todos}, "id": "w"}
                    ],
                ),
                "planned",
            ]
        ),
        tools=[],
        middleware=[TodoListMiddleware()],
        checkpointer=saver,
        state_schema=DeepAgentState,
    )
    config = {"configurable": {"thread_id": "t-todos"}}
    await graph.ainvoke({"messages": [("user", "plan")]}, config)

    state = await get_checkpoint_state(saver, "t-todos")
    assert state.todos == todos
    assert state.structured_response is None


@pytest.mark.asyncio
async def test_reader_is_empty_for_an_unknown_thread():
    state = await get_checkpoint_state(InMemorySaver(), "nope")
    assert state is EMPTY_STATE
    assert state.saved is None
    assert state.messages == [] and state.todos == []
    assert state.structured_response is None
