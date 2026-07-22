"""GCS-backed persistence for Cloud Run sandbox filesystem snapshots.

A Cloud Run sandbox only lives inside one instance; its writable overlay is
exported as a tar at the end of each agent turn and restored on reconnect,
possibly on a different instance. Auth is ADC (the Cloud Run service account).
"""

from __future__ import annotations

from functools import lru_cache

from google.api_core.exceptions import NotFound
from google.cloud import storage

from app.sandbox.settings import sandbox_settings


@lru_cache(maxsize=1)
def _client() -> storage.Client:
    return storage.Client()


def _blob(sandbox_id: str) -> storage.Blob:
    settings = sandbox_settings.cloudrun
    bucket = _client().bucket(settings.gcs_bucket)
    return bucket.blob(f"{settings.snapshot_prefix}{sandbox_id}.tar")


def save_snapshot(sandbox_id: str, tar_bytes: bytes) -> None:
    _blob(sandbox_id).upload_from_string(tar_bytes, content_type="application/x-tar")


def load_snapshot(sandbox_id: str) -> bytes | None:
    if sandbox_settings.cloudrun.gcs_bucket is None:
        return None
    try:
        return _blob(sandbox_id).download_as_bytes()
    except NotFound:
        return None
