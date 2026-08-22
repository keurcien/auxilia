"""Cloud Run sandbox lifecycle: detached launch, same-instance reconnect,
and cross-instance restore from a GCS snapshot."""

from __future__ import annotations

import uuid

from app.sandbox.cloudrun.backend import CloudRunSandbox
from app.sandbox.cloudrun.snapshots import SnapshotStore
from app.sandbox.cloudrun.transport import GatewayTransport, SandboxTransport
from app.sandbox.provider import BaseSandboxProvider
from app.sandbox.schemas import CloudRunConfig


class CloudRunProvider(BaseSandboxProvider):
    config: CloudRunConfig

    def __init__(self, config: CloudRunConfig) -> None:
        super().__init__(config)
        self._transport: SandboxTransport = GatewayTransport(config.url, config.secret)
        self._snapshots = SnapshotStore(
            bucket=config.gcs_bucket, prefix=config.snapshot_prefix
        )

    def _create_backend(self, *, timeout_minutes: int) -> CloudRunSandbox:
        """Cloud Run sandboxes have no TTL — `timeout_minutes` is accepted
        for tool-contract parity and ignored; lifetime is bounded by the
        host instance, with GCS snapshots covering continuity."""
        sandbox_id = f"sbx-{uuid.uuid4().hex[:12]}"
        self._transport.launch(sandbox_id, allow_egress=self.config.allow_egress)
        return CloudRunSandbox(
            sandbox_id,
            timeout=self.config.timeout,
            transport=self._transport,
            snapshot_store=self._snapshots,
        )

    def _destroy_backend(self, backend: CloudRunSandbox) -> None:
        backend.delete()

    def connect(self, sandbox_id: str) -> tuple[CloudRunSandbox, str]:
        backend = CloudRunSandbox(
            sandbox_id,
            timeout=self.config.timeout,
            transport=self._transport,
            snapshot_store=self._snapshots,
        )
        if backend.is_alive():
            return backend, f"Reconnected to sandbox {sandbox_id}."

        tar = self._snapshots.load(sandbox_id)
        if tar is None:
            raise RuntimeError(
                f"sandbox {sandbox_id} no longer exists and has no snapshot"
            )
        # No default-package reinstall on restore: pip writes landed on the
        # overlay, so they travel inside the snapshot.
        self._transport.launch(
            sandbox_id, allow_egress=self.config.allow_egress, import_tar=tar
        )
        return backend, f"Restored sandbox {sandbox_id} from its last snapshot."
