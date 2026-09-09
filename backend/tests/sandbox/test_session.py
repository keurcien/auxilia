"""`open_sandbox`: the runtime, not the model, owns the sandbox lifecycle."""

from unittest.mock import MagicMock

import pytest

from app.exceptions import SandboxUnavailableError
from app.sandbox.provider import (
    DEFAULT_TIMEOUT_MINUTES,
    SandboxGoneError,
    SandboxSession,
    open_sandbox,
)
from tests.sandbox.stub_sandbox import StubSandbox


def _provider(*, connect=None, create_id="sbx-new"):
    provider = MagicMock()
    provider.unavailable.side_effect = lambda reason: SandboxUnavailableError(
        "row", "Test", reason
    )
    provider.create.return_value = (StubSandbox(create_id), "created")
    if connect is not None:
        provider.connect.side_effect = connect
    return provider


def test_reconnects_the_threads_sandbox():
    provider = _provider(connect=lambda sid: (StubSandbox(sid), "reconnected"))

    session = open_sandbox(provider, "sbx-old")

    assert session.sandbox_id == "sbx-old"
    assert session.replaced is False
    provider.create.assert_not_called()


def test_creates_when_the_thread_has_none():
    provider = _provider()

    session = open_sandbox(provider, None)

    assert session.sandbox_id == "sbx-new"
    assert session.replaced is False
    provider.connect.assert_not_called()
    provider.create.assert_called_once_with(timeout_minutes=DEFAULT_TIMEOUT_MINUTES)


def test_replaces_a_sandbox_that_is_gone():
    """Gone and unrestorable is the one failure we recover from — and the
    caller learns about it, because the model has to be told."""
    provider = _provider(connect=SandboxGoneError("no snapshot"))

    session = open_sandbox(provider, "sbx-old")

    assert session.sandbox_id == "sbx-new"
    assert session.replaced is True


def test_other_connect_failures_fail_the_run_as_unavailable():
    """A provider outage must not be papered over with a fresh sandbox — and
    it surfaces as the same typed error the pre-flight gate raises."""
    provider = _provider(connect=ConnectionError("gateway down"))

    with pytest.raises(SandboxUnavailableError, match="gateway down"):
        open_sandbox(provider, "sbx-old")
    provider.create.assert_not_called()


def test_persist_reaches_backends_that_support_it():
    backend = StubSandbox()
    SandboxSession(backend=backend, sandbox_id=backend.id).persist()
    assert backend.persisted == 1

    plain = MagicMock(spec=[])  # no persist attribute
    SandboxSession(backend=plain, sandbox_id="x").persist()  # must not raise
