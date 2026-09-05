"""ProtocolEmitter: the wire grammar the web client consumes, produced from
langgraph's native `astream_events(version="v3")` stream.

The end-to-end tests drive a *real* `create_agent` graph (our `build_runnable`,
with a HITL-gated tool, a subagent behind the deepagents `task` tool and a
checkpointer) with a scripted chat model, so they exercise the actual v3
envelopes the worker sees. The unit tests feed synthetic envelopes to
`ProtocolEmitter.translate` for the edge cases a scripted run can't reach.
These encode the client contract (see the module docstring of `emit.py`); a
change that breaks them breaks the frontend.
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.stream.transformers import UpdatesTransformer
from langgraph.types import Command, Interrupt, Overwrite

from app.agents.protocol.emit import ProtocolEmitter
from app.agents.runtime import build_agent_middleware, build_runnable


# ── A scripted, streaming chat model ────────────────────────────────────


class ScriptedModel(BaseChatModel):
    """Streams one scripted AIMessage per call, word by word, tool-call args
    in two chunks — the shapes a real provider produces."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _next(self) -> AIMessage:
        msg = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return msg

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _chunks(self, msg: AIMessage) -> Iterator[ChatGenerationChunk]:
        content = msg.content if isinstance(msg.content, str) else ""
        words = content.split(" ") if content else []
        for i, w in enumerate(words):
            piece = w if i == len(words) - 1 else w + " "
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece, id=msg.id))
        for index, tc in enumerate(msg.tool_calls):
            args = json.dumps(tc["args"])
            half = len(args) // 2
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    id=msg.id,
                    tool_call_chunks=[
                        {
                            "id": tc["id"],
                            "name": tc["name"],
                            "args": args[:half],
                            "index": index,
                        }
                    ],
                )
            )
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    id=msg.id,
                    tool_call_chunks=[
                        {"id": None, "name": None, "args": args[half:], "index": index}
                    ],
                )
            )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id=msg.id,
                usage_metadata={
                    "input_tokens": 3,
                    "output_tokens": 5,
                    "total_tokens": 8,
                },
            )
        )

    def _stream(
        self,
        messages,
        stop=None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ):
        for chunk in self._chunks(self._next()):
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    async def _astream(
        self,
        messages,
        stop=None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._chunks(self._next()):
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk


@tool(response_format="content_and_artifact")
def get_weather(city: str) -> tuple[str, dict]:
    """Weather for a city."""
    return json.dumps({"temperature": 22, "city": city}), {"mcp_server_id": "s1"}


def _data(event: dict) -> dict:
    return event["params"]["data"]


def _of(
    events: list[dict], method: str, namespace: list[str] | None = None
) -> list[dict]:
    return [
        e
        for e in events
        if e["method"] == method
        and (namespace is None or e["params"]["namespace"] == namespace)
    ]


def _kinds(events: list[dict]) -> list[str]:
    return [_data(e)["event"] for e in events]


async def _collect(agent, agent_input, config) -> list[dict]:
    # Same stream configuration as `Agent.stream` (updates are opt-in).
    run = await agent.astream_events(
        agent_input, config, version="v3", transformers=[UpdatesTransformer]
    )
    out: list[dict] = []
    async with run:
        async for event in ProtocolEmitter().stream(run):
            # Round-trip through JSON: everything on the wire must encode.
            json.dumps(event, default=str)
            out.append(event)
    return out


@pytest.fixture
def scenario():
    """A root agent that delegates to a subagent, then calls a HITL-gated
    tool (interrupting), then answers after the resume."""
    now = datetime.now(UTC)
    helper = CompiledSubAgent(
        name="helper",
        description="helper: helps",
        runnable=build_runnable(
            model=ScriptedModel(
                script=[AIMessage(content="sub says hello", id="sub-ai-1")]
            ),
            tools=[],
            system_prompt="you are a helper",
            base_middleware=build_agent_middleware(now, recursion_limit=25),
        ),
    )
    root_model = ScriptedModel(
        script=[
            AIMessage(
                content="",
                id="root-ai-1",
                tool_calls=[
                    {
                        "id": "call_task_1",
                        "name": "task",
                        "args": {
                            "description": "research X",
                            "subagent_type": "helper",
                        },
                    }
                ],
            ),
            AIMessage(
                content="Let me check the weather.",
                id="root-ai-2",
                tool_calls=[
                    {"id": "call_w_1", "name": "get_weather", "args": {"city": "Paris"}}
                ],
            ),
            AIMessage(content="It is 22 degrees in Paris.", id="root-ai-3"),
        ]
    )
    checkpointer = MemorySaver()
    agent = build_runnable(
        model=root_model,
        tools=[get_weather],
        system_prompt="you are root",
        base_middleware=build_agent_middleware(
            now, recursion_limit=50, interrupt_on={"get_weather": True}
        ),
        subagents=[helper],
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "emit-test"}, "recursion_limit": 50}
    return agent, config, checkpointer


@tool
def send_email(to: str) -> str:
    """Send an email."""
    return f"sent to {to}"


@pytest.fixture
def subagent_scenario():
    """A root agent that delegates to a subagent whose own tool is HITL-gated:
    the subagent pauses mid-`task`, the root answers after the resume."""
    now = datetime.now(UTC)
    mailer = CompiledSubAgent(
        name="mailer",
        description="mailer: sends mail",
        runnable=build_runnable(
            model=ScriptedModel(
                script=[
                    AIMessage(
                        content="",
                        id="sub-ai-1",
                        tool_calls=[
                            {
                                "id": "sub_call_1",
                                "name": "send_email",
                                "args": {"to": "a@b.c"},
                            }
                        ],
                    ),
                    AIMessage(content="mail sent", id="sub-ai-2"),
                ]
            ),
            tools=[send_email],
            system_prompt="you send mail",
            base_middleware=build_agent_middleware(
                now, recursion_limit=25, interrupt_on={"send_email": True}
            ),
        ),
    )
    root_model = ScriptedModel(
        script=[
            AIMessage(
                content="",
                id="root-ai-1",
                tool_calls=[
                    {
                        "id": "call_task_1",
                        "name": "task",
                        "args": {"description": "mail them", "subagent_type": "mailer"},
                    }
                ],
            ),
            AIMessage(content="Done.", id="root-ai-2"),
        ]
    )
    checkpointer = MemorySaver()
    agent = build_runnable(
        model=root_model,
        tools=[],
        system_prompt="you are root",
        base_middleware=build_agent_middleware(
            now, recursion_limit=50, interrupt_on={}
        ),
        subagents=[mailer],
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "emit-sub-test"}, "recursion_limit": 50}
    return agent, config, checkpointer


# ── End to end: a real v3 run ─────────────────────────────────────────────


async def test_run_opens_with_root_started_and_running(scenario):
    agent, config, _ = scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    root_lifecycle = _kinds(_of(events, "lifecycle", []))
    # The client's loading tracker flips `isLoading` only on `running`; the
    # terminal is owned by `finalize`, never emitted here.
    assert root_lifecycle == ["started", "running"]


async def test_text_and_tool_call_message_grammar(scenario):
    agent, config, _ = scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    root_messages = _of(events, "messages", [])
    ai_starts = [
        _data(e) for e in root_messages if _data(e)["event"] == "message-start"
    ]
    assert [s["role"] for s in ai_starts if s["role"] == "ai"] == ["ai", "ai"]
    # Streamed text: block start, deltas, finish carrying the full text.
    text_deltas = [
        _data(e)["delta"]["text"]
        for e in root_messages
        if _data(e)["event"] == "content-block-delta"
        and _data(e)["delta"].get("type") == "text-delta"
    ]
    assert "".join(text_deltas) == "Let me check the weather."
    finishes = [
        _data(e)["content"]
        for e in root_messages
        if _data(e)["event"] == "content-block-finish"
    ]
    assert {"type": "text", "text": "Let me check the weather."} in finishes
    # Streamed tool-call chunks are sealed into parsed `tool_call` blocks.
    assert any(
        c["type"] == "tool_call"
        and c["id"] == "call_w_1"
        and c["args"] == {"city": "Paris"}
        for c in finishes
    )
    # Every message closes, with usage.
    message_finishes = [
        _data(e) for e in root_messages if _data(e)["event"] == "message-finish"
    ]
    assert any(f.get("usage", {}).get("total_tokens") == 8 for f in message_finishes)
    # Events carry the producing node.
    assert all(
        e["params"].get("node") == "model"
        for e in root_messages
        if _data(e)["event"] == "content-block-delta"
    )


async def test_human_input_is_echoed_once(scenario):
    """The input human message never streams on `messages`; it is echoed from
    the root `values` snapshots — once, though every superstep repeats it."""
    agent, config, _ = scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi there", id="human-1")]}, config
    )
    human_starts = [
        _data(e)
        for e in _of(events, "messages", [])
        if _data(e)["event"] == "message-start" and _data(e)["role"] == "human"
    ]
    assert len(human_starts) == 1
    assert human_starts[0]["id"] == "human-1"
    idx = events.index(
        next(
            e
            for e in events
            if e["method"] == "messages" and _data(e).get("id") == "human-1"
        )
    )
    assert _data(events[idx + 1]) == {
        "event": "content-block-start",
        "index": 0,
        "content": {"type": "text", "text": "hi there"},
    }
    assert _data(events[idx + 2])["event"] == "message-finish"


async def test_values_are_trimmed_and_interrupt_becomes_input_requested(scenario):
    agent, config, checkpointer = scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    for values in _of(events, "values", []):
        assert "messages" not in _data(values)
        assert "files" not in _data(values)
        assert "__interrupt__" not in _data(values)
    assert any("run_tool_call_count" in _data(v) for v in _of(events, "values", []))

    [requested] = _of(events, "input.requested")
    assert requested["params"]["namespace"] == []
    payload = _data(requested)["payload"]
    assert payload["action_requests"][0]["name"] == "get_weather"
    # The id matches the checkpoint's pending interrupt — what `input.respond`
    # (PR #307) addresses.
    checkpoint = await checkpointer.aget_tuple(config)
    [(_, channel, value)] = checkpoint.pending_writes
    assert channel == "__interrupt__"
    assert value[0].id == _data(requested)["interrupt_id"]


async def test_tools_channel_and_tool_role_messages(scenario):
    agent, config, _ = scenario
    first = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    # The `task` call: started with its input, finished with the subagent's
    # answer (unwrapped from the Command the task tool returns).
    task_events = [
        e for e in _of(first, "tools", []) if _data(e)["tool_call_id"] == "call_task_1"
    ]
    assert _kinds(task_events) == ["tool-started", "tool-finished"]
    assert _data(task_events[0])["tool_name"] == "task"
    assert _data(task_events[0])["input"] == {
        "description": "research X",
        "subagent_type": "helper",
    }
    assert _data(task_events[1])["output"] == "sub says hello"
    # …and a closed tool-role message so the client's message projection
    # shows the result.
    tool_starts = [
        _data(e)
        for e in _of(first, "messages", [])
        if _data(e)["event"] == "message-start" and _data(e)["role"] == "tool"
    ]
    assert [t["tool_call_id"] for t in tool_starts] == ["call_task_1"]

    # Resume: the gated tool runs, its MCP artifact rides INSIDE `output`.
    second = await _collect(
        agent, Command(resume={"decisions": [{"type": "approve"}]}), config
    )
    weather = [
        e for e in _of(second, "tools", []) if _data(e)["tool_call_id"] == "call_w_1"
    ]
    assert _kinds(weather) == ["tool-started", "tool-finished"]
    assert _data(weather[0])["input"] == {"city": "Paris"}
    assert _data(weather[1])["output"] == {
        "content": '{"temperature": 22, "city": "Paris"}',
        "artifact": {"mcp_server_id": "s1"},
    }
    assert "artifact" not in _data(weather[1])  # never as an extension field
    # No interrupt this time; the resumed run streams the final answer.
    assert _of(second, "input.requested") == []
    assert (
        "".join(
            _data(e)["delta"]["text"]
            for e in _of(second, "messages", [])
            if _data(e)["event"] == "content-block-delta"
        )
        == "It is 22 degrees in Paris."
    )


async def test_subagent_namespace_lifecycle_and_binding_snapshot(scenario):
    agent, config, _ = scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    namespaced = [e for e in events if e["params"]["namespace"]]
    assert namespaced, "the task subagent must stream under its own namespace"
    ns = namespaced[0]["params"]["namespace"]
    assert len(ns) == 1 and ns[0].startswith("tools:")

    lifecycle = _of(events, "lifecycle", ns)
    assert _kinds(lifecycle) == ["started", "completed"]
    started = _data(lifecycle[0])
    assert started["graph_name"] == "helper"
    assert started["cause"] == {"type": "toolCall", "tool_call_id": "call_task_1"}

    # The first namespaced snapshot keeps exactly the first human message —
    # the client binds `tools:<task-id>` to its `task` call by that text —
    # and later snapshots drop messages.
    values = _of(events, "values", ns)
    assert len(values) >= 2
    assert _data(values[0])["messages"] == [
        {
            "type": "human",
            "content": "research X",
            "id": _data(values[0])["messages"][0]["id"],
        }
    ]
    assert all("messages" not in _data(v) for v in values[1:])

    # Subagent tokens stream under the namespace, not the root.
    sub_text = "".join(
        _data(e)["delta"]["text"]
        for e in _of(events, "messages", ns)
        if _data(e)["event"] == "content-block-delta"
    )
    assert sub_text == "sub says hello"


async def test_rejected_tool_call_is_completed_with_tool_error(scenario):
    """A denied approval never runs the tool, so no tool callback fires; the
    middleware writes the rejection ToolMessage straight into state. The
    client's tool card must still be closed — a `tool-error` completes it —
    or it spins for ever."""
    agent, config, _ = scenario
    await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    events = await _collect(
        agent, Command(resume={"decisions": [{"type": "reject"}]}), config
    )
    weather = [
        e for e in _of(events, "tools", []) if _data(e)["tool_call_id"] == "call_w_1"
    ]
    assert _kinds(weather) == ["tool-started", "tool-error"]
    assert "rejected" in _data(weather[1])["message"].lower()
    # …and exactly once, though every later snapshot repeats the message.
    tool_role_starts = [
        e
        for e in _of(events, "messages", [])
        if _data(e)["event"] == "message-start"
        and _data(e).get("tool_call_id") == "call_w_1"
    ]
    assert len(tool_role_starts) == 1


async def test_subagent_interrupt_is_requested_under_its_namespace(subagent_scenario):
    """A subagent's approval: `input.requested` carries the subagent's
    namespace (the client pins it to that card), exactly once even though the
    root's `values` repeats the interrupt, and its id is the root checkpoint's
    pending interrupt — what the id-keyed resume addresses."""
    agent, config, checkpointer = subagent_scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    [requested] = _of(events, "input.requested")
    ns = requested["params"]["namespace"]
    assert len(ns) == 1 and ns[0].startswith("tools:")
    payload = _data(requested)["payload"]
    assert payload["action_requests"][0]["name"] == "send_email"

    checkpoint = await checkpointer.aget_tuple(config)
    [(task_id, channel, value)] = checkpoint.pending_writes
    assert channel == "__interrupt__"
    assert value[0].id == _data(requested)["interrupt_id"]
    assert ns == [f"tools:{task_id}"]

    # The subagent's own lifecycle reports the pause.
    assert _kinds(_of(events, "lifecycle", ns)) == ["started", "interrupted"]


async def test_bubbling_interrupt_does_not_fail_the_task_call(subagent_scenario):
    """langgraph reports the interrupt bubbling through `task` to the parent's
    tool callbacks as a `tool-error`; forwarded, the client would mark the
    subagent card errored for the length of the pause. The call stays open
    and completes normally on the resumed run."""
    agent, config, _ = subagent_scenario
    events = await _collect(
        agent, {"messages": [HumanMessage(content="hi", id="human-1")]}, config
    )
    task_events = [
        e for e in _of(events, "tools", []) if _data(e)["tool_call_id"] == "call_task_1"
    ]
    assert _kinds(task_events) == ["tool-started"]

    resumed = await _collect(
        agent, Command(resume={"decisions": [{"type": "approve"}]}), config
    )
    assert _of(resumed, "input.requested") == []
    ns = next(e["params"]["namespace"] for e in resumed if e["params"]["namespace"])
    sub_tool = [
        e for e in _of(resumed, "tools", ns) if _data(e)["tool_call_id"] == "sub_call_1"
    ]
    assert "tool-finished" in _kinds(sub_tool)
    task_events = [
        e
        for e in _of(resumed, "tools", [])
        if _data(e)["tool_call_id"] == "call_task_1"
    ]
    assert _kinds(task_events)[-1] == "tool-finished"
    assert _kinds(_of(resumed, "lifecycle", ns)) == ["started", "completed"]


def _started(emitter, tool_call_id, tool_name):
    emitter.translate(
        _envelope(
            "tools",
            [],
            {
                "event": "tool-started",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "input": {},
            },
        )
    )


def _errored(emitter, tool_call_id, message):
    return emitter.translate(
        _envelope(
            "tools",
            [],
            {"event": "tool-error", "tool_call_id": tool_call_id, "message": message},
        )
    )


def test_tool_error_that_is_an_interrupt_repr_is_swallowed():
    iid = "ab" * 16
    repr_ = f"(Interrupt(value={{'action_requests': []}}, id='{iid}'),)"
    emitter = ProtocolEmitter()
    _started(emitter, "call_task", "task")
    # The subagent's values envelope announced the interrupt first.
    emitter.translate(
        _envelope(
            "values",
            ["tools:t1"],
            {},
            interrupts=(Interrupt(value={"action_requests": []}, id=iid),),
        )
    )
    assert _errored(emitter, "call_task", repr_) == []
    # A genuine failure of the same call is still reported…
    assert _kinds(_errored(emitter, "call_task", "boom")) == ["tool-error"]


def test_only_the_task_tools_own_interrupt_is_swallowed():
    iid = "ab" * 16
    repr_ = f"(Interrupt(value={{}}, id='{iid}'),)"
    emitter = ProtocolEmitter()
    emitter.translate(
        _envelope("values", ["tools:t1"], {}, interrupts=(Interrupt(value={}, id=iid),))
    )
    # …a non-`task` tool raising the same shape is a failure…
    _started(emitter, "call_w", "get_weather")
    assert _kinds(_errored(emitter, "call_w", repr_)) == ["tool-error"]
    # …an error that merely mentions the id is a failure…
    _started(emitter, "call_task", "task")
    assert _kinds(_errored(emitter, "call_task", f"state dump: {iid}")) == [
        "tool-error"
    ]
    # …and an interrupt id nobody announced is not ours to hide.
    _started(emitter, "call_task_2", "task")
    other = f"(Interrupt(value={{}}, id='{'cd' * 16}'),)"
    assert _kinds(_errored(emitter, "call_task_2", other)) == ["tool-error"]


async def test_graph_failure_propagates_after_buffered_events():
    """A raising graph must surface to the worker (which finalizes the run as
    `error`), not be swallowed into an event."""
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class S(TypedDict):
        x: int

    def boom(state):
        raise RuntimeError("node exploded")

    graph = (
        StateGraph(S)
        .add_node("boom", boom)
        .add_edge(START, "boom")
        .add_edge("boom", END)
    )
    compiled = graph.compile()
    run = await compiled.astream_events({"x": 1}, {}, version="v3")
    seen: list[dict] = []
    with pytest.raises(RuntimeError, match="node exploded"):
        async with run:
            async for event in ProtocolEmitter().stream(run):
                seen.append(event)
    assert _kinds(_of(seen, "lifecycle", [])) == ["started", "running"]


# ── Unit: envelope translation edge cases ────────────────────────────────────


def _envelope(method: str, namespace: list[str], data: Any, **params) -> dict:
    return {
        "type": "event",
        "method": method,
        "params": {"namespace": namespace, "timestamp": 0, "data": data, **params},
    }


def test_error_tool_message_becomes_tool_error_and_is_deduped():
    emitter = ProtocolEmitter()
    output = ToolMessage(
        content="boom", tool_call_id="call-1", id="tm-1", status="error"
    )
    events = emitter.translate(
        _envelope(
            "tools",
            [],
            {"event": "tool-finished", "tool_call_id": "call-1", "output": output},
        )
    )
    tools = _of(events, "tools")
    assert _kinds(tools) == ["tool-error"]
    assert _data(tools[0])["message"] == "boom"
    # A second completion for the same call (a retry replay) is ignored.
    assert (
        emitter.translate(
            _envelope(
                "tools",
                [],
                {"event": "tool-finished", "tool_call_id": "call-1", "output": output},
            )
        )
        == []
    )


def test_updates_complete_tool_calls_that_never_ran_and_are_not_forwarded():
    """A node that writes a ToolMessage into state without running a tool (a
    denied approval, a patched dangling call) gets its completion from the
    node's `updates` delta; a call the channel already completed is not
    reported twice; the delta itself never reaches the wire."""
    emitter = ProtocolEmitter()
    ran = ToolMessage(content="ok", tool_call_id="ran-1", id="tm-ran")
    emitter.translate(
        _envelope(
            "tools",
            [],
            {"event": "tool-finished", "tool_call_id": "ran-1", "output": ran},
        )
    )
    denied = ToolMessage(
        content="User rejected the tool call for `send_email` with id call-2",
        tool_call_id="call-2",
        id="tm-2",
        status="error",
    )
    events = emitter.translate(
        _envelope("updates", [], {"model": {"messages": [ran, denied]}})
    )
    # The denied call is announced before it is completed — the client's
    # assembler ignores a completion for a call it never saw start.
    assert [(e["method"], _data(e)["event"]) for e in events] == [
        ("tools", "tool-started"),
        ("messages", "message-start"),
        ("messages", "content-block-start"),
        ("messages", "message-finish"),
        ("tools", "tool-error"),
    ]
    assert _data(events[0])["tool_call_id"] == "call-2"
    assert _data(events[-1]) == {
        "event": "tool-error",
        "tool_call_id": "call-2",
        "message": "User rejected the tool call for `send_email` with id call-2",
    }
    assert (
        emitter.translate(_envelope("updates", [], {"model": {"messages": [denied]}}))
        == []
    )


def test_plain_tool_output_is_forwarded_untouched():
    events = ProtocolEmitter().translate(
        _envelope(
            "tools",
            [],
            {"event": "tool-finished", "tool_call_id": "c", "output": {"rows": 3}},
        )
    )
    assert [(e["method"], _data(e)["event"]) for e in events] == [
        ("tools", "tool-finished")
    ]
    assert _data(events[0])["output"] == {"rows": 3}


def test_whole_ai_message_is_replayed_as_a_message_lifecycle():
    """A node that returns a finalized AIMessage (middleware fallbacks) is
    replayed as start/block/finish — with its own id."""
    msg = AIMessage(content="Model call failed after 3 attempts", id="fallback-1")
    events = ProtocolEmitter().translate(
        _envelope("messages", [], (msg, {"langgraph_node": "model"}))
    )
    kinds = _kinds(events)
    assert kinds[0] == "message-start" and kinds[-1] == "message-finish"
    assert _data(events[0]) == {
        "event": "message-start",
        "role": "ai",
        "id": "fallback-1",
    }
    assert any(
        _data(e)["event"] == "content-block-finish"
        and _data(e)["content"]
        == {"type": "text", "text": "Model call failed after 3 attempts"}
        for e in events
    )


def test_block_content_and_idless_human_messages_are_not_echoed():
    emitter = ProtocolEmitter()
    rich = HumanMessage(
        content=[
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "x"}},
        ],
        id="human-2",
    )
    anonymous = HumanMessage(content="hi", id="")
    events = emitter.translate(_envelope("values", [], {"messages": [rich, anonymous]}))
    assert [e["method"] for e in events] == ["values"]


def test_values_unwrap_overwrite_and_drop_files():
    events = ProtocolEmitter().translate(
        _envelope(
            "values",
            [],
            {
                "messages": [],
                "files": {"a.txt": "…"},
                "todos": Overwrite([{"content": "x"}]),
            },
        )
    )
    assert _data(events[0]) == {"todos": [{"content": "x"}]}


def test_interrupts_are_deduped_by_id():
    emitter = ProtocolEmitter()
    interrupt = Interrupt(value={"action_requests": []}, id="ab" * 16)
    first = emitter.translate(_envelope("values", [], {}, interrupts=(interrupt,)))
    second = emitter.translate(_envelope("values", [], {}, interrupts=(interrupt,)))
    assert _kinds([]) == []
    assert [e["method"] for e in first] == ["values", "input.requested"]
    assert _data(first[1]) == {
        "interrupt_id": "ab" * 16,
        "payload": {"action_requests": []},
    }
    assert [e["method"] for e in second] == ["values"]


def test_namespaced_lifecycle_is_readdressed_and_drained_maps_to_completed():
    emitter = ProtocolEmitter()
    payload = {
        "event": "started",
        "namespace": ["tools:t1"],
        "graph_name": "helper",
        "trigger_call_id": "t1",
        "cause": {"type": "toolCall", "tool_call_id": "call-1"},
    }
    [started] = emitter.translate(_envelope("lifecycle", [], payload))
    assert started["params"]["namespace"] == ["tools:t1"]
    assert _data(started) == {
        "event": "started",
        "graph_name": "helper",
        "cause": {"type": "toolCall", "tool_call_id": "call-1"},
    }
    [drained] = emitter.translate(
        _envelope("lifecycle", [], {"event": "drained", "namespace": ["tools:t1"]})
    )
    assert _data(drained) == {"event": "completed"}
    [failed] = emitter.translate(
        _envelope(
            "lifecycle",
            [],
            {"event": "failed", "namespace": ["tools:t1"], "error": "x"},
        )
    )
    assert _data(failed) == {"event": "failed", "error": "x"}
    # Root lifecycle is owned by the emitter/finalize, never forwarded.
    assert (
        emitter.translate(
            _envelope("lifecycle", [], {"event": "completed", "namespace": []})
        )
        == []
    )


def test_synthetic_ai_message_events():
    msg = AIMessage(content="I reached my step limit", id="synthetic-1")
    events = ProtocolEmitter.synthetic_ai_message(
        msg, {"messages": [msg], "todos": [], "files": {}}
    )
    assert _kinds(_of(events, "messages"))[0] == "message-start"
    assert _data(events[0])["id"] == "synthetic-1"
    [values] = _of(events, "values")
    assert _data(values) == {"todos": []}
