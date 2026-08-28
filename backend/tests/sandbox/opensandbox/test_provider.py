"""Unit tests for the OpenSandbox provider (SDK mocked)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.sandbox.opensandbox.provider import OpenSandboxProvider
from app.sandbox.schemas import OpenSandboxConfig


@pytest.fixture
def sdk_sandbox():
    sandbox = MagicMock()
    sandbox.get_info.return_value = MagicMock(id="osb-1")
    return sandbox


def make_provider(**overrides) -> OpenSandboxProvider:
    defaults = {"url": "sandbox.example.com", "default_packages": []}
    return OpenSandboxProvider(OpenSandboxConfig(**{**defaults, **overrides}))


def test_create_returns_backend_and_ttl_message(sdk_sandbox):
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        backend, message = make_provider().create(timeout_minutes=45)

    assert backend.id == "osb-1"
    assert "osb-1" in message
    assert "TTL: 45min" in message
    assert sdk.create.call_args.kwargs["timeout"].total_seconds() == 45 * 60


def test_create_installs_default_packages(sdk_sandbox):
    installed = {}
    with (
        patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk,
        patch(
            "app.sandbox.provider.install_default_packages",
            lambda backend, packages: installed.update({"packages": packages}),
        ),
    ):
        sdk.create.return_value = sdk_sandbox
        make_provider(default_packages=["httpx", "rich"]).create(timeout_minutes=30)

    assert installed["packages"] == ["httpx", "rich"]


def test_create_kills_sandbox_when_install_fails(sdk_sandbox):
    with (
        patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk,
        patch(
            "app.sandbox.provider.install_default_packages",
            side_effect=RuntimeError("install failed"),
        ),
    ):
        sdk.create.return_value = sdk_sandbox
        with pytest.raises(RuntimeError, match="install failed"):
            make_provider(default_packages=["httpx"]).create(timeout_minutes=30)

    sdk_sandbox.kill.assert_called_once()


def test_create_passes_parsed_volume_mounts(sdk_sandbox, tmp_path):
    host_dir = tmp_path / "shared"
    host_dir.mkdir()
    provider = make_provider(
        volume_mounts=[
            f"{host_dir}:/mnt/shared:ro",
            "missing:",
            "/does/not/exist:/mnt/x",
        ]
    )
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        provider.create(timeout_minutes=30)

    [volume] = sdk.create.call_args.kwargs["volumes"]
    assert volume.host.path == str(host_dir)
    assert volume.mount_path == "/mnt/shared"
    assert volume.read_only is True


def test_volume_mount_ro_without_sandbox_path_is_skipped(sdk_sandbox):
    """ "/data:ro" must be skipped with a warning, not crash on parts[1]."""
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        make_provider(volume_mounts=["/data:ro"]).create(timeout_minutes=30)
    assert sdk.create.call_args.kwargs["volumes"] is None


def test_relative_volume_mount_is_resolved(sdk_sandbox, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        make_provider(volume_mounts=["data:/mnt/data"]).create(timeout_minutes=30)

    [volume] = sdk.create.call_args.kwargs["volumes"]
    assert Path(volume.host.path).is_absolute()
    assert volume.host.path == str(tmp_path / "data")


def test_create_without_mounts_passes_none(sdk_sandbox):
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        make_provider().create(timeout_minutes=30)
    assert sdk.create.call_args.kwargs["volumes"] is None


def test_connection_config_uses_url_and_secret(sdk_sandbox):
    provider = make_provider(
        url="sbx.internal", secret="sk-key", use_server_proxy=False
    )
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.create.return_value = sdk_sandbox
        provider.create(timeout_minutes=30)

    connection = sdk.create.call_args.kwargs["connection_config"]
    assert connection.domain == "sbx.internal"
    assert connection.api_key == "sk-key"
    assert connection.use_server_proxy is False


def test_connect_renews_ttl(sdk_sandbox):
    with patch("app.sandbox.opensandbox.provider.SandboxSync") as sdk:
        sdk.connect.return_value = sdk_sandbox
        _backend, message = make_provider().connect("osb-1")

    sdk.connect.assert_called_once()
    sdk_sandbox.renew.assert_called_once()
    assert "TTL renewed" in message
