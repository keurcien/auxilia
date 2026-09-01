"""ProtocolService: command envelopes and replay-cursor derivation.

DB-backed verbs (`run.start` / `input.respond` land in `RunService`, already
covered by the runs tests); here we pin the protocol-level surface: envelope
shapes for unknown/unsupported methods, seq derivation, and the SSE frame.
"""

import json

import pytest

from app.agents.protocol.schemas import ProtocolCommand
from app.agents.protocol.service import (
    ProtocolService,
    _sentinel_status,
    _seq_for_entry,
    _wrap,
)
from app.agents.runs.events import end_sentinel
from app.agents.runs.state import RunStatus
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


async def test_input_respond_requires_an_interrupt_id():
    with pytest.raises(DomainValidationError):
        await _service().dispatch(
            "t1",
            "u1",
            ProtocolCommand(id=1, method="input.respond", params={"response": {}}),
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
    a = _seq_for_entry("1725000000123-0")
    b = _seq_for_entry("1725000000123-1")
    c = _seq_for_entry("1725000000124-0")
    assert a < b < c
    assert c < 2**53  # JS Number.MAX_SAFE_INTEGER
    # Synthetic entry ids (expired-log terminals) degrade to 0, not a crash.
    assert _seq_for_entry("not-a-stream-id") == 0


def test_sentinel_status_round_trips():
    assert (
        _sentinel_status(end_sentinel(RunStatus.interrupted)) is RunStatus.interrupted
    )
    assert _sentinel_status('event: end\ndata: {"status": "future"}\n\n') is None


def test_wrap_produces_a_protocol_event_envelope():
    frame = _wrap(
        {
            "method": "lifecycle",
            "params": {"namespace": [], "data": {"event": "started"}},
        },
        event_id="123-0.0",
        seq=42,
    )
    assert frame.startswith("id: 123-0.0\ndata: ")
    payload = json.loads(frame.split("data: ", 1)[1])
    assert payload["type"] == "event"
    assert payload["event_id"] == "123-0.0"
    assert payload["seq"] == 42
    assert payload["method"] == "lifecycle"
