from typing import Literal

from pydantic_settings import BaseSettings

from app.sandbox.cloudrun.settings import CloudRunSandboxSettings
from app.sandbox.opensandbox.settings import OpenSandboxSettings
from app.settings import ROOT_ENV


class SandboxProviderSettings(BaseSettings):
    """Provider selector, shared by both sandbox backends."""

    provider: Literal["opensandbox", "cloudrun"] = "opensandbox"

    model_config = {"env_file": ROOT_ENV, "env_prefix": "SANDBOX_", "extra": "ignore"}


class SandboxSettings:
    """Facade over the provider selector and both provider configs.

    Keeps the two call sites the rest of the app relies on stable:
    `sandbox_settings.enabled` (gates the deep-agent path) and
    `sandbox_settings.provider` (picks the provider in provider.py).
    """

    def __init__(self) -> None:
        self.provider = SandboxProviderSettings().provider
        self.opensandbox = OpenSandboxSettings()
        self.cloudrun = CloudRunSandboxSettings()

    @property
    def enabled(self) -> bool:
        if self.provider == "cloudrun":
            # The gateway service is the only way to reach sandboxes.
            # GCS snapshots are optional (best-effort).
            return self.cloudrun.gateway_url is not None
        return self.opensandbox.domain is not None


sandbox_settings = SandboxSettings()
