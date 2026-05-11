import pytest

from app.agents.runs.state import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    IllegalTransitionError,
    RunEvent,
    RunState,
    is_active,
    is_terminal,
    transition,
)


class TestPartitions:
    def test_active_and_terminal_are_disjoint(self):
        assert ACTIVE_STATES.isdisjoint(TERMINAL_STATES)

    def test_every_state_is_active_xor_terminal(self):
        assert ACTIVE_STATES | TERMINAL_STATES == set(RunState)

    @pytest.mark.parametrize("state", list(RunState))
    def test_is_active_matches_partition(self, state):
        assert is_active(state) == (state in ACTIVE_STATES)
        assert is_terminal(state) == (state in TERMINAL_STATES)


class TestHappyPath:
    def test_pending_dequeued_running(self):
        assert transition(RunState.PENDING, RunEvent.DEQUEUED) == RunState.RUNNING

    def test_running_completed_success(self):
        assert transition(RunState.RUNNING, RunEvent.COMPLETED) == RunState.SUCCESS

    def test_running_interrupt_emitted_interrupted(self):
        assert (
            transition(RunState.RUNNING, RunEvent.INTERRUPT_EMITTED)
            == RunState.INTERRUPTED
        )

    def test_running_timed_out_timeout(self):
        assert transition(RunState.RUNNING, RunEvent.TIMED_OUT) == RunState.TIMEOUT


class TestCancellationPaths:
    @pytest.mark.parametrize(
        "source", [RunState.PENDING, RunState.RUNNING, RunState.INTERRUPTED]
    )
    def test_active_states_can_be_cancelled(self, source):
        assert transition(source, RunEvent.CANCELLED) == RunState.CANCELLED

    @pytest.mark.parametrize("terminal", list(TERMINAL_STATES))
    def test_terminal_states_cannot_be_cancelled(self, terminal):
        with pytest.raises(IllegalTransitionError):
            transition(terminal, RunEvent.CANCELLED)


class TestErrorPaths:
    @pytest.mark.parametrize(
        "source", [RunState.PENDING, RunState.RUNNING, RunState.INTERRUPTED]
    )
    def test_active_states_can_error(self, source):
        assert transition(source, RunEvent.ERRORED) == RunState.ERROR


class TestIllegalTransitions:
    @pytest.mark.parametrize(
        "source",
        [RunState.SUCCESS, RunState.ERROR, RunState.CANCELLED, RunState.TIMEOUT],
    )
    @pytest.mark.parametrize("event", list(RunEvent))
    def test_terminal_states_reject_all_events(self, source, event):
        with pytest.raises(IllegalTransitionError) as exc_info:
            transition(source, event)
        assert exc_info.value.current == source
        assert exc_info.value.event == event

    def test_pending_cannot_be_interrupted_directly(self):
        # Interrupts only emerge from a running graph
        with pytest.raises(IllegalTransitionError):
            transition(RunState.PENDING, RunEvent.INTERRUPT_EMITTED)

    def test_pending_cannot_complete_directly(self):
        with pytest.raises(IllegalTransitionError):
            transition(RunState.PENDING, RunEvent.COMPLETED)

    def test_interrupted_cannot_be_dequeued(self):
        # Resume creates a new run; the old one stays interrupted.
        with pytest.raises(IllegalTransitionError):
            transition(RunState.INTERRUPTED, RunEvent.DEQUEUED)
