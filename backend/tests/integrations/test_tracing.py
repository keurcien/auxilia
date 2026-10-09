import builtins
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.integrations import tracing
from app.observability.service import ObservabilityRuntimeConfig


def _config() -> ObservabilityRuntimeConfig:
    return ObservabilityRuntimeConfig(
        base_url="https://langfuse.test",
        public_key="pk-test",
        secret_key="sk-test",
        timeout_seconds=15,
        revision=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("configured", [False, True])
def test_missing_sdk_does_not_prevent_runs(monkeypatch, configured):
    """No provider imports when disabled; missing installed SDK fails open."""
    original_import = builtins.__import__
    provider_imports = []

    def without_provider(name, *args, **kwargs):
        if name == "app.integrations.langfuse.tracing":
            provider_imports.append(name)
            raise ImportError("optional SDK unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_provider)
    config = _config() if configured else None
    integration = tracing.get_tracing(config)
    assert isinstance(integration, tracing.NoOpTracing)
    assert integration.callbacks == []
    with integration.run_context(session_id="thread", user_id="user"):
        pass
    assert bool(provider_imports) == configured


def test_configured_adapter_receives_runtime_config(monkeypatch):
    from app.integrations.langfuse import tracing as langfuse_tracing

    adapter = MagicMock()
    factory = MagicMock(return_value=adapter)
    monkeypatch.setattr(langfuse_tracing, "create_tracing", factory)
    config = _config()

    assert tracing.get_tracing(config) is adapter
    factory.assert_called_once_with(config)


def test_shutdown_does_not_initialize_tracing(monkeypatch):
    from app.integrations.langfuse import callback

    factory = MagicMock()
    monkeypatch.setattr(callback, "flush_langfuse", factory)
    tracing.flush_tracing()
    factory.assert_called_once_with()


def test_tracing_failure_does_not_break_shutdown(monkeypatch):
    from app.integrations.langfuse import callback

    monkeypatch.setattr(
        callback,
        "flush_langfuse",
        MagicMock(side_effect=RuntimeError("export unavailable")),
    )
    tracing.flush_tracing()
