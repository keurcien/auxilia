from pydantic_settings import BaseSettings

from app.settings import ROOT_ENV


class CloudRunSandboxSettings(BaseSettings):
    """Cloud Run sandboxes are driven over HTTP via the dedicated gateway
    service (`gateway_url`, see sandbox-gateway/ at the repo root) — the
    only deployment that runs the `sandbox` CLI. Snapshots of the writable
    overlay are persisted to GCS between agent turns when `gcs_bucket` is
    set, because a sandbox only lives inside one gateway instance.
    """

    gcs_bucket: str | None = None
    allow_egress: bool = False
    snapshot_prefix: str = "sandbox-snapshots/"
    default_packages: list[str] = []
    timeout: int = 30 * 60
    gateway_url: str | None = None
    # Shared secret: the gateway service requires it on every request; the
    # GatewayTransport sends it as a bearer token.
    gateway_secret: str | None = None

    model_config = {
        "env_file": ROOT_ENV,
        "env_prefix": "CLOUD_RUN_SANDBOX_",
        "extra": "ignore",
    }
