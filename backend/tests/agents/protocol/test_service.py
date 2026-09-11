"""ProtocolService: command envelopes; the wire codec's replay cursors.

DB-backed verbs (`run.start` / `input.respond` land in `RunService`, already
covered by the runs tests); here we pin the protocol-level surface: envelope
shapes for unknown/unsupported methods, seq derivation, the SSE frame, and
the stored-event codec.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Overwrite

import app.agents.protocol.service as service_mod
from app.agents.checkpoints import EMPTY_STATE
from app.agents.protocol.schemas import ProtocolCommand
from app.agents.protocol.service import ProtocolService
from app.agents.protocol.wire import (
    decode_event,
    encode_event,
    encode_terminal,
    frame,
    seq_for_entry,
)
from app.exceptions import DomainValidationError, NotFoundError
from tests.agents.fake_checkpoints import checkpoint_state


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
    """What `alist` yields: enough of a checkpoint tuple to name its namespace
    and carry the root's pending writes."""

    def __init__(self, ns: str, pending_writes: list | None = None):
        self.config = {"configurable": {"checkpoint_ns": ns}}
        self.pending_writes = pending_writes or []


@pytest.fixture(autouse=True)
def _route_fake_checkpointers(monkeypatch):
    """The service and `hitl` read state through `get_checkpoint_state`; the
    fakes below answer it per namespace via `state_for`."""
    import app.agents.hitl as hitl_mod
    from app.agents.protocol import service as service_mod

    async def _get(checkpointer, thread_id, checkpoint_ns=""):
        return checkpointer.state_for(checkpoint_ns)

    monkeypatch.setattr(service_mod, "get_checkpoint_state", _get)
    monkeypatch.setattr(hitl_mod, "get_checkpoint_state", _get)


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

    def state_for(self, checkpoint_ns: str):
        if checkpoint_ns == "":
            return checkpoint_state(self._root, pending_writes=self._writes)
        if checkpoint_ns in self._namespaces:
            return checkpoint_state(self._namespaces[checkpoint_ns])
        return EMPTY_STATE

    async def alist(self, config):
        if config["configurable"].get("checkpoint_ns") == "":
            yield _Tuple("", self._writes)
            return
        for ns in self._namespaces:
            yield _Tuple(ns)


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

    def state_for(self, checkpoint_ns: str):
        return self.by_ns.get(checkpoint_ns, EMPTY_STATE)


def _paused(messages, interrupt_id, task_id):
    return checkpoint_state(
        messages, interrupts=[(task_id, {"action_requests": []}, interrupt_id)]
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


# ---------------------------------------------------------------------------
# GET /threads/{id}/messages/{message_id} — one message, whole, off the writes
# ---------------------------------------------------------------------------


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _writes_repo(values):
    """A `CheckpointWriteRepository` stand-in streaming real serde blobs of
    `values` (what langgraph stores per task on the `messages` channel) and
    counting how many the caller consumed."""
    serde = JsonPlusSerializer()
    consumed = []

    class _Repo:
        def __init__(self, db):
            pass

        async def iter_message_writes(self, thread_id):
            for v in values:
                consumed.append(v)
                yield serde.dumps_typed(v)

    return _Repo, consumed


@pytest.mark.asyncio
async def test_message_is_read_from_the_writes_without_the_state(monkeypatch):
    big = ToolMessage(content="x" * 50_000, tool_call_id="c2", id="t2")
    repo, consumed = _writes_repo(
        [
            [AIMessage(content="later", id="a3")],  # newest checkpoint first
            [big],
            Overwrite([HumanMessage(content="hi", id="h1")]),
        ]
    )
    monkeypatch.setattr(service_mod, "CheckpointWriteRepository", repo)
    monkeypatch.setattr(service_mod, "AsyncSessionLocal", lambda: _Session())

    async def _never(*_a, **_k):
        raise AssertionError("the state must not be materialised")

    monkeypatch.setattr(service_mod, "get_checkpointer", _never)

    d = await _service().message("t1", "t2")

    assert d["id"] == "t2" and d["content"] == "x" * 50_000
    assert len(consumed) == 2, "scanning stops at the first matching write"


@pytest.mark.asyncio
async def test_message_inside_an_overwrite_write_is_found(monkeypatch):
    repo, _ = _writes_repo([Overwrite([HumanMessage(content="hi", id="h1")])])
    monkeypatch.setattr(service_mod, "CheckpointWriteRepository", repo)
    monkeypatch.setattr(service_mod, "AsyncSessionLocal", lambda: _Session())
    assert (await _service().message("t1", "h1"))["content"] == "hi"


@pytest.mark.asyncio
async def test_message_falls_back_to_the_state_when_the_writes_are_gone(monkeypatch):
    repo, _ = _writes_repo([])
    monkeypatch.setattr(service_mod, "CheckpointWriteRepository", repo)
    monkeypatch.setattr(service_mod, "AsyncSessionLocal", lambda: _Session())
    checkpointer = _Checkpointer(
        [ToolMessage(content="old", tool_call_id="c", id="t9")], {}
    )
    monkeypatch.setattr(
        "app.agents.protocol.service.get_checkpointer", _checkpointer_cm(checkpointer)
    )
    assert (await _service().message("t1", "t9"))["content"] == "old"
    with pytest.raises(NotFoundError):
        await _service().message("t1", "nope")
