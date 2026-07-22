"""Cloud Run sandbox lifecycle: detached launch, same-instance reconnect,
and cross-instance restore from a GCS snapshot."""

from __future__ import annotations

import uuid

from app.sandbox.cloudrun import snapshots
from app.sandbox.cloudrun.backend import CloudRunSandbox
from app.sandbox.cloudrun.transport import get_transport
from app.sandbox.provider import install_default_packages
from app.sandbox.settings import sandbox_settings


class CloudRunProvider:
    def create(self, *, timeout_minutes: int) -> tuple[CloudRunSandbox, str]:
        """Cloud Run sandboxes have no TTL — `timeout_minutes` is accepted
        for tool-contract parity and ignored; lifetime is bounded by the
        host instance, with GCS snapshots covering continuity."""
        settings = sandbox_settings.cloudrun
        sandbox_id = f"sbx-{uuid.uuid4().hex[:12]}"
        transport = get_transport()
        transport.launch(sandbox_id, allow_egress=settings.allow_egress)
        backend = CloudRunSandbox(
            sandbox_id, timeout=settings.timeout, transport=transport
        )
        try:
            install_default_packages(backend, list(settings.default_packages))
        except Exception:
            # Don't leak a running sandbox the caller never got an ID for.
            backend.delete()
            raise
        return backend, f"Sandbox created (ID: {sandbox_id}). You can now execute code."

    def connect(self, sandbox_id: str) -> tuple[CloudRunSandbox, str]:
        settings = sandbox_settings.cloudrun
        transport = get_transport()
        backend = CloudRunSandbox(
            sandbox_id, timeout=settings.timeout, transport=transport
        )
        if backend.is_alive():
            return backend, f"Reconnected to sandbox {sandbox_id}."

        tar = snapshots.load_snapshot(sandbox_id)
        if tar is None:
            raise RuntimeError(
                f"sandbox {sandbox_id} no longer exists and has no snapshot"
            )
        # No default-package reinstall on restore: pip writes landed on the
        # overlay, so they travel inside the snapshot.
        transport.launch(sandbox_id, allow_egress=settings.allow_egress, import_tar=tar)
        return backend, f"Restored sandbox {sandbox_id} from its last snapshot."
