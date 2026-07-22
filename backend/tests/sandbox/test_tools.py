"""Unit tests for the provider-agnostic sandbox lifecycle tools."""

from unittest.mock import MagicMock

import pytest

from app.sandbox.lazy import LazySandboxBackend
from app.sandbox.tools import create_sandbox_tools


class FakeProvider:
    def __init__(self):
        self.backend = MagicMock(id="sbx-new")
        self.connect_error: Exception | None = None

    def create(self, *, timeout_minutes):
        self.created_with = timeout_minutes
        return self.backend, f"Sandbox created (ID: {self.backend.id})."

    def connect(self, sandbox_id):
        if self.connect_error is not None:
            raise self.connect_error
        return self.backend, f"Reconnected to sandbox {sandbox_id}."


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.sandbox.tools.get_provider", lambda: fake)
    return fake


@pytest.fixture
def lazy_backend():
    return LazySandboxBackend()


def tool_by_name(tools, name):
    return next(t for t in tools if t.name == name)


def test_tool_names(provider, lazy_backend):
    tools = create_sandbox_tools(lazy_backend)
    assert {t.name for t in tools} == {"create_sandbox", "connect_sandbox"}


def test_create_connects_lazy_backend(provider, lazy_backend):
    tools = create_sandbox_tools(lazy_backend)
    result = tool_by_name(tools, "create_sandbox").invoke({"timeout_minutes": 45})

    assert "sbx-new" in result
    assert provider.created_with == 45
    assert lazy_backend._backend is provider.backend


def test_connect_success(provider, lazy_backend):
    tools = create_sandbox_tools(lazy_backend)
    result = tool_by_name(tools, "connect_sandbox").invoke({"sandbox_id": "sbx-x"})

    assert "Reconnected to sandbox sbx-x" in result
    assert lazy_backend._backend is provider.backend


def test_connect_error_is_reported_not_raised(provider, lazy_backend):
    provider.connect_error = RuntimeError("sandbox gone")
    tools = create_sandbox_tools(lazy_backend)
    result = tool_by_name(tools, "connect_sandbox").invoke({"sandbox_id": "sbx-x"})

    assert "sandbox gone" in result
    assert "Create a new sandbox instead" in result
    assert lazy_backend.connected is False
