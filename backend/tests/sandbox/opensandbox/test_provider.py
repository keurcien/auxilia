"""Unit tests for the OpenSandbox provider (SDK mocked)."""

from pathlib import Path
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


def test_create_kills_sandbox_when_install_fails(sdk_sandbox, monkeypatch):
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", ["httpx"])
    with (
        patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk,
        patch(
            "app.sandbox.opensandbox.provider.install_default_packages",
            side_effect=RuntimeError("install failed"),
        ),
    ):
        sdk.create.return_value = sdk_sandbox
        with pytest.raises(RuntimeError, match="install failed"):
            OpenSandboxProvider().create(timeout_minutes=30)

    sdk_sandbox.kill.assert_called_once()


def test_create_passes_parsed_volume_mounts(sdk_sandbox, monkeypatch, tmp_path):
    host_dir = tmp_path / "shared"
    host_dir.mkdir()
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", [])
    monkeypatch.setattr(
        sandbox_settings.opensandbox,
        "volume_mounts",
        f"{host_dir}:/mnt/shared:ro,missing:,/does/not/exist:/mnt/x",
    )
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        OpenSandboxProvider().create(timeout_minutes=30)

    [volume] = sdk.create.call_args.kwargs["volumes"]
    assert volume.host.path == str(host_dir)
    assert volume.mount_path == "/mnt/shared"
    assert volume.read_only is True


def test_volume_mount_ro_without_sandbox_path_is_skipped(sdk_sandbox, monkeypatch):
    """ "/data:ro" must be skipped with a warning, not crash on parts[1]."""
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", [])
    monkeypatch.setattr(sandbox_settings.opensandbox, "volume_mounts", "/data:ro")
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        OpenSandboxProvider().create(timeout_minutes=30)
    assert sdk.create.call_args.kwargs["volumes"] is None


def test_relative_volume_mount_is_resolved(sdk_sandbox, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", [])
    monkeypatch.setattr(sandbox_settings.opensandbox, "volume_mounts", "data:/mnt/data")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        OpenSandboxProvider().create(timeout_minutes=30)

    [volume] = sdk.create.call_args.kwargs["volumes"]
    assert Path(volume.host.path).is_absolute()
    assert volume.host.path == str(tmp_path / "data")


def test_create_without_mounts_passes_none(sdk_sandbox, monkeypatch):
    monkeypatch.setattr(sandbox_settings.opensandbox, "default_packages", [])
    monkeypatch.setattr(sandbox_settings.opensandbox, "volume_mounts", "")
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        OpenSandboxProvider().create(timeout_minutes=30)
    assert sdk.create.call_args.kwargs["volumes"] is None


def test_connect_renews_ttl(sdk_sandbox):
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.connect.return_value = sdk_sandbox
        backend, message = OpenSandboxProvider().connect("osb-1")

    sdk.connect.assert_called_once()
    sdk_sandbox.renew.assert_called_once()
    assert "TTL renewed" in message
