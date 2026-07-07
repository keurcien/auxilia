import pytest

from app.agents.runs.state import (
    TERMINAL_STATUSES,
    InvalidRunTransitionError,
    RunStatus,
    is_terminal,
    transition,
)


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
