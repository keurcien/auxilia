"""ProtocolService: command envelopes; the wire codec's replay cursors.

DB-backed verbs (`run.start` / `input.respond` land in `RunService`, already
covered by the runs tests); here we pin the protocol-level surface: envelope
shapes for unknown/unsupported methods, seq derivation, the SSE frame, and
the stored-event codec.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.protocol.schemas import ProtocolCommand
from app.agents.protocol.service import ProtocolService
from app.agents.protocol.wire import (
    decode_event,
    encode_event,
    encode_terminal,
    frame,
    seq_for_entry,
)
from app.exceptions import DomainValidationError


class _NoRedis:
    """`ProtocolService(redis=…)` never touches Redis for pure dispatches."""


def _service() -> ProtocolService:
    return ProtocolService(redis=_NoRedis())


async def test_unknown_method_is_a_protocol_error_envelope():
    response = await _service().dispatch(
        "t1", "u1", ProtocolCommand(id=7, method="run.selfdestruct", params={})
    )
    assert response == {
        "type": "error",
        "id": 7,
        "error": "unknown_command",
        "message": "Unknown method 'run.selfdestruct'.",
    }


async def test_known_but_unsupported_method_is_not_supported():
    response = await _service().dispatch(
        "t1", "u1", ProtocolCommand(id=3, method="state.fork", params={})
    )
    assert response["type"] == "error"
    assert response["error"] == "not_supported"


async def test_input_respond_requires_a_response_or_interrupt_id():
    """A bare input.respond with neither field is malformed; either one alone
    is dispatchable (a missing interrupt id falls back to the positional
    resume path for pre-interrupt-id checkpoints)."""
    with pytest.raises(DomainValidationError):
        await _service().dispatch(
            "t1",
            "u1",
            ProtocolCommand(id=1, method="input.respond", params={}),
        )


async def test_run_start_rejects_non_object_config():
    for bad in ("gpt-4o", 0, False, ""):
        with pytest.raises(DomainValidationError):
            await _service().dispatch(
                "t1",
                "u1",
                ProtocolCommand(
                    id=1, method="run.start", params={"input": {}, "config": bad}
                ),
            )


async def test_input_respond_batch_form_requires_exactly_one_entry():
    with pytest.raises(DomainValidationError):
        await _service().dispatch(
            "t1",
            "u1",
            ProtocolCommand(
                id=1, method="input.respond", params={"responses": [{}, {}]}
            ),
        )


def test_seq_is_monotonic_and_js_safe():
    a = seq_for_entry("1725000000123-0")
    b = seq_for_entry("1725000000123-1")
    c = seq_for_entry("1725000000124-0")
    assert a < b < c
    assert c < 2**53  # JS Number.MAX_SAFE_INTEGER
    # 13-bit counter: a same-millisecond burst keeps strictly increasing seqs…
    assert (
        seq_for_entry("1725000000123-1000")
        < seq_for_entry("1725000000123-5000")
        < seq_for_entry("1725000000124-0")
    )
    # …and a hypothetical overflow saturates into ties, never reordering.
    assert seq_for_entry("1725000000123-8191") == seq_for_entry("1725000000123-99999")
    # Synthetic entry ids (expired-log terminals) degrade to 0, not a crash.
    assert seq_for_entry("not-a-stream-id") == 0


def test_frame_produces_a_protocol_event_envelope():
    sse = frame(
        {
            "method": "lifecycle",
            "params": {"namespace": [], "data": {"event": "started"}},
        },
        run_id="run-a",
        entry_id="1725000000123-0",
    )
    # Redis stream ids are unique per stream only; the run id makes the
    # event id unique across the several runs one thread session relays.
    assert sse.startswith("id: run-a:1725000000123-0\ndata: ")
    payload = json.loads(sse.split("data: ", 1)[1])
    assert payload["type"] == "event"
    assert payload["event_id"] == "run-a:1725000000123-0"
    assert payload["seq"] == seq_for_entry("1725000000123-0")
    assert payload["method"] == "lifecycle"


def test_stored_events_round_trip_and_legacy_entries_are_skipped():
    event = {
        "method": "values",
        "params": {"namespace": [], "timestamp": 1, "data": {}},
    }
    assert decode_event(encode_event(event)) == event
    # A pre-protocol SSE chunk (a run in flight during the deploy) is not ours.
    assert decode_event("event: messages\ndata: [{}, {}]\n\n") is None
    assert decode_event("") is None
    assert decode_event('{"no": "method"}') is None


def test_terminal_entries_map_run_statuses():
    def terminal(status, error=None):
        return decode_event(encode_terminal(status, error=error))["params"]["data"]

    assert terminal("success") == {"event": "completed"}
    assert terminal("cancelled") == {"event": "completed"}  # a Stop is not a failure
    assert terminal("interrupted") == {"event": "interrupted"}
    assert terminal("error", "boom") == {"event": "failed", "error": "boom"}
    assert terminal("timeout") == {"event": "failed"}
    # A status this build doesn't know (a newer producer mid-deploy) must
    # surface as failed — never as a false completed.
    assert terminal("brand-new-status") == {"event": "failed"}


# --- thread history -------------------------------------------------------------


class _Tuple:
    def __init__(self, ns: str, messages: list, pending_writes: list | None = None):
        self.config = {"configurable": {"checkpoint_ns": ns}}
        self.checkpoint = {"channel_values": {"messages": messages}}
        self.pending_writes = pending_writes or []


class _Checkpointer:
    """Root state plus subagent namespaces keyed by pregel task ids.

    `task_writes` maps a pregel task id to the tool_call_id it answered — the
    root checkpoint's pending writes."""

    def __init__(
        self,
        root: list,
        namespaces: dict[str, list],
        task_writes: dict[str, str] | None = None,
    ):
        self._root = root
        self._namespaces = namespaces
        self._writes = [
            (task_id, "messages", ToolMessage(content="done", tool_call_id=call_id))
            for task_id, call_id in (task_writes or {}).items()
        ]

    async def aget_tuple(self, config):
        return _Tuple("", self._root, self._writes)

    async def alist(self, config):
        if config["configurable"].get("checkpoint_ns") == "":
            yield _Tuple("", self._root, self._writes)
            return
        for ns, messages in self._namespaces.items():
            yield _Tuple(ns, messages)

    async def aget(self, config):
        ns = config["configurable"].get("checkpoint_ns")
        if ns in self._namespaces:
            return {"channel_values": {"messages": self._namespaces[ns]}}
        return None


def _checkpointer_cm(checkpointer):
    class _CM:
        async def __aenter__(self):
            return checkpointer

        async def __aexit__(self, *exc):
            return False

    return lambda: _CM()


def _root_with_task(tool_call_id: str, description: str) -> list:
    return [
        HumanMessage(content="Look into it", id="h1"),
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "id": tool_call_id,
                    "name": "task",
                    "args": {"description": description, "subagent_type": "r"},
                }
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_history_without_a_tools_namespace_is_empty(monkeypatch):
    monkeypatch.setattr(
        "app.agents.protocol.service.get_checkpointer",
        _checkpointer_cm(_Checkpointer([], {})),
    )
    assert await _service().thread_history("t1", None) == []
    assert await _service().thread_history("t1", "research:abc") == []


@pytest.mark.asyncio
async def test_history_resolves_a_task_call_to_its_subgraph_checkpoint(monkeypatch):
    """`tools:<tool_call_id>` → the namespace whose seed message is the task
    description — strictly, so a description that contains another one
    cannot pick the wrong subagent."""
    inner = [HumanMessage(content="Inspect the incident", id="s1"), AIMessage("done")]
    decoy = [HumanMessage(content="Inspect the incident report", id="s2")]
    checkpointer = _Checkpointer(
        _root_with_task("call_1", "Inspect the incident"),
        {"tools:task-b": decoy, "tools:task-a": inner},
    )
    monkeypatch.setattr(
        "app.agents.protocol.service.get_checkpointer", _checkpointer_cm(checkpointer)
    )

    page = await _service().thread_history("t1", "tools:call_1")

    assert len(page) == 1
    state = page[0]
    assert state["checkpoint"] == {"checkpoint_ns": "tools:call_1"}
    assert state["next"] == [] and state["tasks"] == []
    assert [m["content"] for m in state["values"]["messages"]] == [
        "Inspect the incident",
        "done",
    ]


@pytest.mark.asyncio
async def test_history_for_an_unknown_task_call_is_empty(monkeypatch):
    checkpointer = _Checkpointer(_root_with_task("call_1", "x"), {"tools:t": []})
    monkeypatch.setattr(
        "app.agents.protocol.service.get_checkpointer", _checkpointer_cm(checkpointer)
    )
    assert await _service().thread_history("t1", "tools:call_9") == []


@pytest.mark.asyncio
async def test_history_maps_duplicate_descriptions_by_task_id(monkeypatch):
    """Two task calls with the same description resolve through the root
    checkpoint's pending writes (task id → tool_call_id), not by text."""
    root = [
        HumanMessage(content="go", id="h1"),
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {"id": cid, "name": "task", "args": {"description": "Read the deck"}}
                for cid in ("call_1", "call_2")
            ],
        ),
    ]
    first = [HumanMessage(content="Read the deck"), AIMessage("first result")]
    second = [HumanMessage(content="Read the deck"), AIMessage("second result")]
    checkpointer = _Checkpointer(
        root,
        {"tools:task-a": first, "tools:task-b": second},
        task_writes={"task-a": "call_1", "task-b": "call_2"},
    )
    monkeypatch.setattr(
        "app.agents.protocol.service.get_checkpointer", _checkpointer_cm(checkpointer)
    )

    svc = _service()
    one = await svc.thread_history("t1", "tools:call_1")
    two = await svc.thread_history("t1", "tools:call_2")

    assert one[0]["values"]["messages"][-1]["content"] == "first result"
    assert two[0]["values"]["messages"][-1]["content"] == "second result"


# ── thread_state: the hydration snapshot names the paused agent ─────────────


class _NsCheckpointer:
    def __init__(self, by_ns):
        self.by_ns = by_ns

    async def aget_tuple(self, config):
        return self.by_ns.get(config["configurable"].get("checkpoint_ns", ""))


def _paused(messages, interrupt_id, task_id):
    from types import SimpleNamespace

    return SimpleNamespace(
        pending_writes=[
            (
                task_id,
                "__interrupt__",
                [SimpleNamespace(value={"action_requests": []}, id=interrupt_id)],
            )
        ],
        checkpoint={"channel_values": {"messages": messages}},
    )


_TASK_CALL = AIMessage(
    content="",
    tool_calls=[
        {
            "id": "call_task",
            "name": "task",
            "args": {"description": "do it", "subagent_type": "w"},
        }
    ],
)


@pytest.mark.parametrize(
    ("by_ns_factory", "expected_namespace"),
    [
        (lambda iid: {"": _paused([], iid, "hitl-task")}, []),
        # The paused subagent's `task` call is known: address the interrupt
        # with the SDK's discovery key, `tools:<tool_call_id>`.
        (
            lambda iid: {
                "": _paused([_TASK_CALL], iid, "task-1"),
                "tools:task-1": _paused([HumanMessage("do it")], iid, "hitl-task"),
            },
            ["tools:call_task"],
        ),
        # No task call to name (older checkpoint): the execution namespace.
        (
            lambda iid: {
                "": _paused([], iid, "task-1"),
                "tools:task-1": _paused([HumanMessage("do it")], iid, "hitl-task"),
            },
            ["tools:task-1"],
        ),
    ],
)
async def test_thread_state_interrupt_carries_the_paused_agents_namespace(
    monkeypatch, by_ns_factory, expected_namespace
):
    """A subagent's interrupt hydrates with its namespace so the client lands
    the approval on that card, exactly as the live `input.requested` does."""
    from contextlib import asynccontextmanager

    from app.agents.protocol import service as service_mod

    iid = "ab" * 16
    checkpointer = _NsCheckpointer(by_ns_factory(iid))

    @asynccontextmanager
    async def _checkpointer():
        yield checkpointer

    monkeypatch.setattr(service_mod, "get_checkpointer", _checkpointer)
    service = _service()

    async def _no_active(_thread_id):
        return None

    monkeypatch.setattr(service.runs, "get_active", _no_active)

    state = await service.thread_state("t1")
    assert state["next"] == ["agent"]
    [task] = state["tasks"]
    assert task["interrupts"] == [
        {"id": iid, "value": {"action_requests": []}, "namespace": expected_namespace}
    ]
