"""Unit tests for the gateway sandbox transport (HTTP mocked)."""

import base64
import json

import httpx
import pytest

from app.sandbox.cloudrun.transport import (
    GatewayTransport,
    SandboxTimeoutError,
    get_transport,
)
from app.sandbox.settings import sandbox_settings


class TestGetTransport:
    def test_raises_without_gateway_url(self, monkeypatch):
        monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_url", None)
        get_transport.cache_clear()
        with pytest.raises(RuntimeError, match="GATEWAY_URL"):
            get_transport()
        get_transport.cache_clear()

    def test_returns_gateway_transport(self, monkeypatch):
        monkeypatch.setattr(
            sandbox_settings.cloudrun, "gateway_url", "http://gateway.test"
        )
        get_transport.cache_clear()
        assert isinstance(get_transport(), GatewayTransport)
        get_transport.cache_clear()


def gateway_with_handler(handler) -> tuple[GatewayTransport, list[httpx.Request]]:
    """A GatewayTransport whose HTTP layer is an in-memory handler."""
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = GatewayTransport("http://gateway.test", "s3cret")
    transport._client = httpx.Client(
        base_url="http://gateway.test",
        headers={"Authorization": "Bearer s3cret"},
        transport=httpx.MockTransport(recording_handler),
    )
    return transport, requests


class TestGatewayTransport:
    def test_launch_posts_payload_with_bearer(self):
        transport, requests = gateway_with_handler(
            lambda request: httpx.Response(201, json={"sandbox_id": "sbx-x"})
        )
        transport.launch("sbx-x", allow_egress=True, import_tar=b"tar")

        [request] = requests
        assert request.url.path == "/sandboxes"
        assert request.headers["authorization"] == "Bearer s3cret"
        body = json.loads(request.content)
        assert body["sandbox_id"] == "sbx-x"
        assert body["allow_egress"] is True
        assert base64.b64decode(body["import_tar_b64"]) == b"tar"

    def test_launch_error_raises_with_detail(self):
        transport, _ = gateway_with_handler(
            lambda request: httpx.Response(502, json={"detail": "cli exploded"})
        )
        with pytest.raises(RuntimeError, match="cli exploded"):
            transport.launch("sbx-x")

    def test_exec_roundtrip(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body == {"argv": ["/bin/bash", "-lc", "echo hi"], "timeout": 5}
            return httpx.Response(
                200,
                json={
                    "stdout_b64": base64.b64encode(b"out").decode(),
                    "stderr_b64": base64.b64encode(b"err").decode(),
                    "exit_code": 3,
                    "timed_out": False,
                },
            )

        transport, requests = gateway_with_handler(handler)
        result = transport.exec("sbx-x", ["/bin/bash", "-lc", "echo hi"], timeout=5)

        assert requests[0].url.path == "/sandboxes/sbx-x/exec"
        assert (result.stdout, result.stderr, result.returncode) == (b"out", b"err", 3)

    def test_exec_timed_out_flag_raises(self):
        transport, _ = gateway_with_handler(
            lambda request: httpx.Response(
                200,
                json={
                    "stdout_b64": "",
                    "stderr_b64": "",
                    "exit_code": None,
                    "timed_out": True,
                },
            )
        )
        with pytest.raises(SandboxTimeoutError):
            transport.exec("sbx-x", ["/bin/true"], timeout=5)

    def test_export_tar_returns_bytes(self):
        transport, requests = gateway_with_handler(
            lambda request: httpx.Response(200, content=b"overlay-tar")
        )
        assert transport.export_tar("sbx-x") == b"overlay-tar"
        assert requests[0].url.path == "/sandboxes/sbx-x/tar"

    def test_delete(self):
        transport, requests = gateway_with_handler(lambda request: httpx.Response(204))
        transport.delete("sbx-x")
        assert requests[0].method == "DELETE"
        assert requests[0].url.path == "/sandboxes/sbx-x"
