"""GCS-backed persistence for Cloud Run sandbox filesystem snapshots.

A Cloud Run sandbox only lives inside one instance; its writable overlay is
exported as a tar at the end of each agent turn and restored on reconnect,
possibly on a different instance. Auth is ADC (the Cloud Run service account).
"""

from __future__ import annotations

from functools import lru_cache

from google.api_core.exceptions import NotFound
from google.cloud import storage


@lru_cache(maxsize=1)
def _client() -> storage.Client:
    return storage.Client()


class SnapshotStore:
    """Snapshot persistence for one sandbox's GCS location (bucket + prefix
    come from the workspace sandbox config). With no bucket configured the
    store is inert: saves are skipped, loads return None."""

    def __init__(self, *, bucket: str | None, prefix: str) -> None:
        self._bucket = bucket
        self._prefix = prefix

    @property
    def enabled(self) -> bool:
        return self._bucket is not None

    def _blob(self, sandbox_id: str) -> storage.Blob:
        bucket = _client().bucket(self._bucket)
        return bucket.blob(f"{self._prefix}{sandbox_id}.tar")

    def save(self, sandbox_id: str, tar_bytes: bytes) -> None:
        if not self.enabled:
            return
        self._blob(sandbox_id).upload_from_string(
            tar_bytes, content_type="application/x-tar"
        )

    def load(self, sandbox_id: str) -> bytes | None:
        if not self.enabled:
            return None
        try:
            return self._blob(sandbox_id).download_as_bytes()
        except NotFound:
            return None
