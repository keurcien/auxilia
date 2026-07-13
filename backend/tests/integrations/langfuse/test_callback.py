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
