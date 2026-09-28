import builtins
from unittest.mock import MagicMock

import pytest

from app.integrations import tracing
from app.integrations.langfuse.settings import langfuse_settings


@pytest.fixture(autouse=True)
def reset_tracing(monkeypatch):
    monkeypatch.setattr(tracing, "_tracing", None)


@pytest.mark.parametrize("configured", [False, True])
def test_missing_sdk_does_not_prevent_runs(monkeypatch, configured):
    """No provider imports when disabled; missing installed SDK fails open."""
    monkeypatch.setattr(langfuse_settings, "langfuse_base_url", "https://langfuse.test")
    monkeypatch.setattr(
        langfuse_settings, "langfuse_public_key", "pk-test" if configured else None
    )
    monkeypatch.setattr(langfuse_settings, "langfuse_secret_key", "sk-test")
    original_import = builtins.__import__
    provider_imports = []

    def without_provider(name, *args, **kwargs):
        if name == "app.integrations.langfuse.tracing":
            provider_imports.append(name)
            raise ImportError("optional SDK unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_provider)
    integration = tracing.get_tracing()
    assert isinstance(integration, tracing.NoOpTracing)
    assert integration.callbacks == []
    with integration.run_context(session_id="thread", user_id="user"):
        pass
    assert bool(provider_imports) == configured
    assert tracing.get_tracing() is integration


def test_configured_adapter_is_reused_and_flushed(monkeypatch):
    from app.integrations.langfuse import tracing as langfuse_tracing

    monkeypatch.setattr(langfuse_settings, "langfuse_base_url", "https://langfuse.test")
    monkeypatch.setattr(langfuse_settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(langfuse_settings, "langfuse_secret_key", "sk-test")
    adapter = MagicMock()
    factory = MagicMock(return_value=adapter)
    monkeypatch.setattr(langfuse_tracing, "create_tracing", factory)

    assert tracing.get_tracing() is adapter
    assert tracing.get_tracing() is adapter
    factory.assert_called_once_with()
    tracing.flush_tracing()
    adapter.flush.assert_called_once_with()


def test_shutdown_does_not_initialize_tracing(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(tracing, "get_tracing", factory)
    tracing.flush_tracing()
    factory.assert_not_called()


def test_tracing_failure_does_not_break_shutdown(monkeypatch):
    adapter = MagicMock()
    adapter.flush.side_effect = RuntimeError("export unavailable")
    monkeypatch.setattr(tracing, "_tracing", adapter)
    tracing.flush_tracing()
