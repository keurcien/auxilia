from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, TypeAdapter, model_validator
from sqlmodel import Field, SQLModel

from app.sandbox.models import SandboxBase, SandboxProviderType


class SandboxConfigBase(SQLModel):
    """Shared shape of every sandbox provider's runtime config.

    Hydrated from a SandboxDB row (url/secret from columns, the rest from the
    config JSONB) or from a create/patch payload. `secret` only ever holds a
    decrypted or client-supplied value in memory — it is never serialized into
    a response or the config column.
    """

    # Unknown keys are rejected, not dropped: silently discarding a config
    # field an admin typed (or one belonging to another provider) would save
    # something different from what they saw.
    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    url: str
    secret: str | None = Field(default=None, exclude=True)
    default_packages: list[str] = []
    timeout: int = Field(default=30 * 60, ge=1)


class OpenSandboxConfig(SandboxConfigBase):
    provider: Literal["opensandbox"] = "opensandbox"
    default_image: str = "python:3.12-slim"
    volume_mounts: list[str] = []
    use_server_proxy: bool = True


class CloudRunConfig(SandboxConfigBase):
    provider: Literal["cloudrun"] = "cloudrun"
    gcs_bucket: str | None = None
    snapshot_prefix: str = "sandbox-snapshots/"
    allow_egress: bool = False

    @model_validator(mode="after")
    def require_secret(self) -> "CloudRunConfig":
        # The gateway fails closed without its shared secret — saving a
        # secretless Cloud Run sandbox would advertise tools that can never
        # work (formerly the boot-time `enabled` check).
        if not self.secret:
            raise ValueError("Cloud Run sandboxes require a gateway secret")
        return self


class DaytonaConfig(SandboxConfigBase):
    provider: Literal["daytona"] = "daytona"
    url: str = "https://app.daytona.io/api"
    target: str = "us"
    snapshot: str | None = None
    auto_stop_interval: int = Field(default=15, ge=0)

    @model_validator(mode="after")
    def require_secret(self) -> "DaytonaConfig":
        if not self.secret:
            raise ValueError("Daytona sandboxes require an API key")
        return self


SandboxConfig = Annotated[
    OpenSandboxConfig | CloudRunConfig | DaytonaConfig,
    Field(discriminator="provider"),
]

_config_adapter: TypeAdapter[SandboxConfig] = TypeAdapter(SandboxConfig)

# Fields stored as first-class columns (or not stored at all), not in the
# config JSONB remainder.
_COLUMN_FIELDS = {"provider", "url", "secret"}


def validate_config(
    provider: SandboxProviderType,
    *,
    url: str,
    secret: str | None,
    config: dict,
) -> SandboxConfigBase:
    """Validate a full provider config through the discriminated union.

    Raises pydantic.ValidationError — callers translate it to a domain error.
    """
    payload = {**config, "provider": provider.value, "url": url, "secret": secret}
    return _config_adapter.validate_python(payload)


def config_extras(validated: SandboxConfigBase) -> dict:
    """The provider-specific remainder persisted to the config JSONB column,
    with defaults materialized."""
    return validated.model_dump(exclude=_COLUMN_FIELDS)


class SandboxCreate(SQLModel):
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=255)
    provider: SandboxProviderType
    url: str
    # Write-only credential: excluded from serialization so it never lands in
    # the row via generic create/update paths — the service encrypts it.
    secret: str | None = Field(default=None, exclude=True)
    config: dict = {}


class SandboxCreateDB(SandboxBase):
    encrypted_secret: str | None = None


class SandboxPatch(SQLModel):
    """Partial update. `provider` is immutable — the config only makes sense
    for the provider it was validated against; recreate to switch. An omitted
    or empty `secret` keeps the stored one (write-only, like OAuth secrets)."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=255)
    url: str | None = None
    secret: str | None = Field(default=None, exclude=True)
    config: dict | None = None


class SandboxResponse(SQLModel):
    id: UUID
    name: str
    description: str | None = None
    provider: SandboxProviderType
    url: str
    config: dict
    has_secret: bool = False
    created_at: datetime
    updated_at: datetime


class SandboxAgentResponse(SQLModel):
    """An agent still bound to a sandbox — shown in the delete-guard dialog."""

    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None


class SandboxSecretHint(SQLModel):
    """Non-reversible hint about the stored credential, so an admin can
    confirm *which* secret is configured without exposing it. Admin-only."""

    is_set: bool = False
    last4: str | None = None
    length: int | None = None
