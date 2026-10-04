from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.integrations.langfuse import callback
from app.observability.service import ObservabilityRuntimeConfig


def _config(*, revision: datetime | None = None) -> ObservabilityRuntimeConfig:
    return ObservabilityRuntimeConfig(
        base_url="https://langfuse.test",
        public_key="pk-test",
        secret_key="sk-test",
        timeout_seconds=21,
        revision=revision or datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_langfuse_client_receives_configured_timeout(monkeypatch):
    langfuse_constructor = MagicMock()
    callback_constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", langfuse_constructor)
    monkeypatch.setattr(callback, "CallbackHandler", callback_constructor)

    client, handler = callback._build_langfuse(_config())

    langfuse_constructor.assert_called_once_with(
        public_key="pk-test",
        secret_key="sk-test",
        host="https://langfuse.test",
        timeout=21,
    )
    callback_constructor.assert_called_once_with(public_key="pk-test")
    assert client is langfuse_constructor.return_value
    assert handler is callback_constructor.return_value


# ---------------------------------------------------------------------------
# lazy construction + shutdown flush (P1-17)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _unbuilt():
    """Reset the client cache so each test observes a first build."""
    callback._clients.clear()
    yield
    callback._clients.clear()


def test_a_broken_langfuse_config_does_not_break_the_agent_runtime(monkeypatch):
    """The regression: this was a module-level constant, and `app/runtime/agent.py` imports
    it — so a bad base URL took down every import of the agent runtime at
    startup, for an optional integration."""
    monkeypatch.setattr(
        callback, "Langfuse", MagicMock(side_effect=ValueError("bad host"))
    )

    assert callback.get_langfuse_callback_handler(_config()) is None


def test_the_client_is_built_once_not_per_run(monkeypatch):
    """`CallbackHandler` is attached to every agent run; rebuilding would mean a
    fresh exporter thread per run."""
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())

    config = _config()
    first = callback.get_langfuse_callback_handler(config)
    second = callback.get_langfuse_callback_handler(config)

    assert first is second
    constructor.assert_called_once()


def test_a_new_configuration_revision_builds_a_new_client(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())

    callback.get_langfuse_callback_handler(_config())
    callback.get_langfuse_callback_handler(
        _config(revision=datetime(2026, 1, 2, tzinfo=UTC))
    )

    assert constructor.call_count == 2


def test_flush_ships_buffered_traces(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", MagicMock(return_value=client))
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())
    callback.get_langfuse_callback_handler(_config())  # build it

    callback.flush_langfuse()

    client.flush.assert_called_once()


def test_flush_does_not_build_a_client_the_process_never_needed(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)

    callback.flush_langfuse()

    constructor.assert_not_called()


def test_a_failing_flush_does_not_fail_shutdown(monkeypatch):
    client = MagicMock()
    client.flush.side_effect = RuntimeError("langfuse unreachable")
    monkeypatch.setattr(callback, "Langfuse", MagicMock(return_value=client))
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())
    callback.get_langfuse_callback_handler(_config())

    callback.flush_langfuse()  # must not raise
