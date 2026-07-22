"""Unit tests for the OpenSandbox provider (SDK mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from app.sandbox.opensandbox.provider import OpenSandboxProvider
from app.sandbox.settings import sandbox_settings


@pytest.fixture
def sdk_sandbox():
    sandbox = MagicMock()
    sandbox.get_info.return_value = MagicMock(id="osb-1")
    return sandbox


def test_create_returns_backend_and_ttl_message(sdk_sandbox, monkeypatch):
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", [])
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        backend, message = OpenSandboxProvider().create(timeout_minutes=45)

    assert backend.id == "osb-1"
    assert "osb-1" in message
    assert "TTL: 45min" in message
    assert sdk.create.call_args.kwargs["timeout"].total_seconds() == 45 * 60


def test_create_installs_default_packages(sdk_sandbox, monkeypatch):
    monkeypatch.setattr(
        sandbox_settings.opensandbox, "default_packages", ["httpx", "rich"]
    )
    installed = {}
    with (
        patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk,
        patch(
            "app.sandbox.opensandbox.provider.install_default_packages",
            lambda backend, packages: installed.update({"packages": packages}),
        ),
    ):
        sdk.create.return_value = sdk_sandbox
        OpenSandboxProvider().create(timeout_minutes=30)

    assert installed["packages"] == ["httpx", "rich"]


def test_connect_renews_ttl(sdk_sandbox):
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.connect.return_value = sdk_sandbox
        backend, message = OpenSandboxProvider().connect("osb-1")

    sdk.connect.assert_called_once()
    sdk_sandbox.renew.assert_called_once()
    assert "TTL renewed" in message
