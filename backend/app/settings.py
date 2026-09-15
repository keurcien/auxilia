"""App-wide settings, and the shared settings config every module reuses."""

from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Unpack


BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BACKEND_DIR.parent / ".env"


def settings_config(**overrides: Unpack[SettingsConfigDict]) -> SettingsConfigDict:
    """The settings config every `BaseSettings` subclass in the app should use.

    Two reasons it lives here rather than being re-declared per module:

    - The `.env` path is derived once. Each module used to count `.parent`s up to
      the repo root, so the resolution silently depended on the file's depth and
      moving a settings file pointed it at a directory that doesn't exist.
      `extra="ignore"` then hid the mistake — the class loaded with defaults.
    - It is a `SettingsConfigDict`. Modules annotated `model_config` as pydantic's
      `ConfigDict`, which is a different TypedDict that has no `env_file` /
      `env_prefix` keys, so a mistyped settings key was invisible to type
      checkers. Pass module-specific keys (e.g. `env_prefix="run_"`) as overrides.
    """
    return SettingsConfigDict(env_file=ROOT_ENV, extra="ignore", **overrides)


class AppSettings(BaseSettings):
    database_url: str = "postgresql+psycopg://auxilia:auxilia@localhost:5432/auxilia"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    backend_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    # "console": plain text for a terminal. "gcp": one JSON object per line in
    # Cloud Logging's structured format (severity/sourceLocation/httpRequest
    # as their own fields) — set this on Cloud Run, leave it alone elsewhere.
    log_format: Literal["console", "gcp"] = "console"
    # Unset restores normal DNS. An IP is a temporary routing workaround, not
    # a stable Google backend version selector.
    mcp_bigquery_pinned_ip: IPv4Address | IPv6Address | None = None

    @field_validator("mcp_bigquery_pinned_ip", mode="before")
    @classmethod
    def empty_pin_is_disabled(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return None if value == "" else value

    model_config = settings_config()


app_settings: AppSettings = AppSettings()
