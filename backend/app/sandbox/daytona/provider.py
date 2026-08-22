"""Daytona sandbox lifecycle: create / reconnect via the Daytona SDK.

Daytona sandboxes are managed server-side (app.daytona.io or a self-hosted
instance): they auto-stop when idle and can be restarted, so `connect`
transparently wakes a stopped or paused sandbox instead of failing.
"""

from __future__ import annotations

from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaConfig as DaytonaSDKConfig,
)

from app.sandbox.daytona.backend import DaytonaSandbox
from app.sandbox.provider import BaseSandboxProvider
from app.sandbox.schemas import DaytonaConfig


# States `connect` can recover from by (re)starting the sandbox.
_WAKEABLE_STATES = {"stopped", "stopping", "paused", "pausing", "archived"}


class DaytonaProvider(BaseSandboxProvider):
    config: DaytonaConfig

    def _client(self) -> Daytona:
        return Daytona(
            DaytonaSDKConfig(
                api_key=self.config.secret,
                api_url=self.config.url,
                target=self.config.target,
            )
        )

    def _create_backend(self, *, timeout_minutes: int) -> DaytonaSandbox:
        """`timeout_minutes` maps to Daytona's idle auto-stop when it exceeds
        the configured interval — the sandbox survives at least that long."""
        auto_stop = max(self.config.auto_stop_interval, timeout_minutes)
        sandbox = self._client().create(
            CreateSandboxFromSnapshotParams(
                snapshot=self.config.snapshot,
                auto_stop_interval=auto_stop,
            )
        )
        return DaytonaSandbox(sandbox, timeout=self.config.timeout)

    def _destroy_backend(self, backend: DaytonaSandbox) -> None:
        backend.delete()

    def connect(self, sandbox_id: str) -> tuple[DaytonaSandbox, str]:
        client = self._client()
        sandbox = client.get(sandbox_id)
        state = str(getattr(sandbox, "state", "") or "").lower()
        if state in _WAKEABLE_STATES:
            client.start(sandbox)
            return (
                DaytonaSandbox(sandbox, timeout=self.config.timeout),
                f"Restarted sandbox {sandbox_id}. Files are preserved.",
            )
        return (
            DaytonaSandbox(sandbox, timeout=self.config.timeout),
            f"Reconnected to sandbox {sandbox_id}.",
        )
