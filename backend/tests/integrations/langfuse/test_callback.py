from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.integrations.langfuse import callback
from app.integrations.langfuse.settings import LangfuseSettings


def test_langfuse_timeout_defaults_to_fifteen_seconds(monkeypatch):
    monkeypatch.delenv("LANGFUSE_TIMEOUT", raising=False)

    settings = LangfuseSettings(_env_file=None)

    assert settings.langfuse_timeout == 15


def test_langfuse_timeout_can_be_configured_from_environment(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TIMEOUT", "21")

    settings = LangfuseSettings(_env_file=None)

    assert settings.langfuse_timeout == 21


@pytest.mark.parametrize("timeout", [0, -1])
def test_langfuse_timeout_must_be_positive(timeout):
    with pytest.raises(ValidationError):
        LangfuseSettings(langfuse_timeout=timeout, _env_file=None)


def test_langfuse_client_receives_configured_timeout(monkeypatch):
    langfuse_constructor = MagicMock()
    callback_constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", langfuse_constructor)
    monkeypatch.setattr(callback, "CallbackHandler", callback_constructor)
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(
        callback.langfuse_settings, "langfuse_base_url", "https://langfuse.test"
    )
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_timeout", 21)

    client, handler = callback._build_langfuse()

    langfuse_constructor.assert_called_once_with(
        public_key="pk-test",
        secret_key="sk-test",
        host="https://langfuse.test",
        timeout=21,
    )
    callback_constructor.assert_called_once_with()
    assert client is langfuse_constructor.return_value
    assert handler is callback_constructor.return_value


# ---------------------------------------------------------------------------
# lazy construction + shutdown flush (P1-17)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _unbuilt(monkeypatch):
    """Reset the module memo so each test observes a first build."""
    monkeypatch.setattr(callback, "_built", False)
    monkeypatch.setattr(callback, "_client", None)
    monkeypatch.setattr(callback, "_handler", None)


def _configure(monkeypatch):
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(
        callback.langfuse_settings, "langfuse_base_url", "https://langfuse.test"
    )


def test_a_broken_langfuse_config_does_not_break_the_agent_runtime(monkeypatch):
    """The regression: this was a module-level constant, and `runtime.py` imports
    it — so a bad base URL took down every import of the agent runtime at
    startup, for an optional integration."""
    _configure(monkeypatch)
    monkeypatch.setattr(
        callback, "Langfuse", MagicMock(side_effect=ValueError("bad host"))
    )

    assert callback.get_langfuse_callback_handler() is None


def test_the_client_is_built_once_not_per_run(monkeypatch):
    """`CallbackHandler` is attached to every agent run; rebuilding would mean a
    fresh exporter thread per run."""
    _configure(monkeypatch)
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())

    first = callback.get_langfuse_callback_handler()
    second = callback.get_langfuse_callback_handler()

    assert first is second
    constructor.assert_called_once()


def test_no_handler_when_unconfigured(monkeypatch):
    monkeypatch.setattr(callback.langfuse_settings, "langfuse_public_key", None)
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)

    assert callback.get_langfuse_callback_handler() is None
    constructor.assert_not_called()


def test_flush_ships_buffered_traces(monkeypatch):
    _configure(monkeypatch)
    client = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", MagicMock(return_value=client))
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())
    callback.get_langfuse_callback_handler()  # build it

    callback.flush_langfuse()

    client.flush.assert_called_once()


def test_flush_does_not_build_a_client_the_process_never_needed(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(callback, "Langfuse", constructor)

    callback.flush_langfuse()

    constructor.assert_not_called()


def test_a_failing_flush_does_not_fail_shutdown(monkeypatch):
    _configure(monkeypatch)
    client = MagicMock()
    client.flush.side_effect = RuntimeError("langfuse unreachable")
    monkeypatch.setattr(callback, "Langfuse", MagicMock(return_value=client))
    monkeypatch.setattr(callback, "CallbackHandler", MagicMock())
    callback.get_langfuse_callback_handler()

    callback.flush_langfuse()  # must not raise
