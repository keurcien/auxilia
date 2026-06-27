import pytest

from app.agents.runs.state import (
    TERMINAL_STATUSES,
    InvalidRunTransitionError,
    RunRecord,
    RunStatus,
    is_terminal,
    transition,
)


def test_record_redis_round_trip():
    record = RunRecord(
        id="r1",
        thread_id="t1",
        user_id="u1",
        input={"messages": [{"type": "human", "content": "hi"}]},
        trigger="regenerate-message",
    )
    back = RunRecord.from_redis(record.to_redis())
    assert back.id == "r1"
    assert back.input == record.input
    assert back.trigger == "regenerate-message"
    assert back.status == RunStatus.pending


def test_to_redis_omits_none_fields():
    raw = RunRecord(id="r1", thread_id="t1", user_id="u1").to_redis()
    assert "error" not in raw
    assert "command" not in raw
    assert "last_heartbeat" not in raw


@pytest.mark.parametrize(
    "current,target",
    [
        (RunStatus.pending, RunStatus.running),
        (RunStatus.pending, RunStatus.cancelled),
        (RunStatus.running, RunStatus.success),
        (RunStatus.running, RunStatus.interrupted),
        (RunStatus.running, RunStatus.timeout),
    ],
)
def test_legal_transitions(current, target):
    assert transition(current, target) == target


@pytest.mark.parametrize(
    "current,target",
    [
        (RunStatus.success, RunStatus.running),
        (RunStatus.running, RunStatus.pending),
        (RunStatus.cancelled, RunStatus.success),
        (RunStatus.interrupted, RunStatus.running),
    ],
)
def test_illegal_transitions_raise(current, target):
    with pytest.raises(InvalidRunTransitionError):
        transition(current, target)


def test_terminal_classification():
    assert is_terminal(RunStatus.success)
    assert is_terminal(RunStatus.interrupted)
    assert not is_terminal(RunStatus.running)
    assert RunStatus.pending not in TERMINAL_STATUSES
