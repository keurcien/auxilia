"""HTTP transport for driving Cloud Run sandboxes.

The `sandbox` CLI lives exclusively on the dedicated gateway Cloud Run
service (``sandbox-gateway/`` at the repo root — the only deployment that
needs ``--sandbox-launcher``); the backend drives it over HTTP with a bearer
token. This keeps the backend fully decoupled from the sandbox host: no CLI
on backend instances, no sandbox resource pressure on them, and identical
behavior whether the backend runs on Cloud Run or a laptop.

``SandboxTransport`` is the seam the backend and provider are written
against; tests substitute fakes for it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.sandbox.settings import sandbox_settings


# Margin added to the gateway HTTP timeout so the in-sandbox command timeout
# (enforced gateway-side) fires first and returns a structured result.
_GATEWAY_TIMEOUT_MARGIN = 30

# Lifecycle operations (launch/tar/delete) get a fixed generous timeout —
# they are control-plane calls, not user code.
_LIFECYCLE_TIMEOUT = 120


class SandboxTimeoutError(Exception):
    """The command hit its timeout before completing."""


@dataclass
class ExecResult:
    stdout: bytes
    stderr: bytes
    returncode: int


class SandboxTransport(Protocol):
    def launch(
        self,
        sandbox_id: str,
        *,
        allow_egress: bool = False,
        import_tar: bytes | None = None,
    ) -> None: ...

    def exec(self, sandbox_id: str, argv: list[str], *, timeout: int) -> ExecResult: ...

    def export_tar(self, sandbox_id: str) -> bytes: ...

    def delete(self, sandbox_id: str) -> None: ...


class GatewayTransport:
    """Drive the `sandbox` CLI on the gateway service over HTTP."""

    def __init__(self, base_url: str, secret: str | None) -> None:
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=_LIFECYCLE_TIMEOUT
        )

    def launch(
        self,
        sandbox_id: str,
        *,
        allow_egress: bool = False,
        import_tar: bytes | None = None,
    ) -> None:
        payload: dict = {"sandbox_id": sandbox_id, "allow_egress": allow_egress}
        if import_tar is not None:
            payload["import_tar_b64"] = base64.b64encode(import_tar).decode("ascii")
        response = self._client.post("/sandboxes", json=payload)
        if response.status_code != 201:
            raise RuntimeError(
                f"Failed to launch sandbox {sandbox_id}: {_error_detail(response)}"
            )

    def exec(self, sandbox_id: str, argv: list[str], *, timeout: int) -> ExecResult:
        try:
            response = self._client.post(
                f"/sandboxes/{sandbox_id}/exec",
                json={"argv": argv, "timeout": timeout},
                timeout=timeout + _GATEWAY_TIMEOUT_MARGIN,
            )
        except httpx.TimeoutException as e:
            raise SandboxTimeoutError() from e
        if response.status_code != 200:
            raise RuntimeError(
                f"Gateway exec failed for {sandbox_id}: {_error_detail(response)}"
            )
        body = response.json()
        if body.get("timed_out"):
            raise SandboxTimeoutError()
        return ExecResult(
            stdout=base64.b64decode(body["stdout_b64"]),
            stderr=base64.b64decode(body["stderr_b64"]),
            returncode=body["exit_code"],
        )

    def export_tar(self, sandbox_id: str) -> bytes:
        response = self._client.get(f"/sandboxes/{sandbox_id}/tar")
        if response.status_code != 200:
            raise RuntimeError(
                f"sandbox tar failed for {sandbox_id}: {_error_detail(response)}"
            )
        return response.content

    def delete(self, sandbox_id: str) -> None:
        self._client.delete(f"/sandboxes/{sandbox_id}")


def _error_detail(response: httpx.Response) -> str:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


@lru_cache(maxsize=1)
def get_transport() -> SandboxTransport:
    """The gateway transport (singleton — it holds a pooled HTTP client)."""
    settings = sandbox_settings.cloudrun
    if settings.gateway_url is None:
        raise RuntimeError(
            "CLOUD_RUN_SANDBOX_GATEWAY_URL is not configured — the cloudrun "
            "sandbox provider requires the sandbox gateway service."
        )
    return GatewayTransport(settings.gateway_url, settings.gateway_secret)
