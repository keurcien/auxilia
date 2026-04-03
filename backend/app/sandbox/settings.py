from pydantic_settings import BaseSettings

from app.settings import ROOT_ENV


class SandboxSettings(BaseSettings):
    domain: str | None = None
    api_key: str | None = None
    default_image: str = "python:3.12-slim"
    default_packages: list[str] = []
    timeout: int = 30 * 60
    volume_mounts: str = ""
    use_server_proxy: bool = True

    model_config = {"env_file": ROOT_ENV, "env_prefix": "OPEN_SANDBOX_", "extra": "ignore"}

    @property
    def parsed_volume_mounts(self) -> list[str]:
        return [entry.strip() for entry in self.volume_mounts.split(",") if entry.strip()]

    @property
    def enabled(self) -> bool:
        return self.domain is not None


sandbox_settings = SandboxSettings()
