from enum import Enum
from uuid import UUID

from sqlalchemy import Column, Index, Text, text
from sqlmodel import Field, UniqueConstraint

from app.models import BaseDBModel


class ModelProviderType(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    anthropic = "anthropic"
    google = "google"
    xiaomi = "xiaomi"
    openrouter = "openrouter"
    meta = "meta"


class ModelDB(BaseDBModel, table=True):
    """A workspace admin's enablement decision for one whitelisted model.

    The DB stores only the decision — model metadata (display name,
    capabilities) lives in the whitelist and is never copied here. Row absent
    = disabled (enablement is explicit opt-in); a row whose model has left
    the whitelist is kept and surfaced as deprecated, never required to be
    deleted.
    """

    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "model_id",
            name="uq_models_workspace_provider_model",
        ),
        # At most one workspace default, enforced by the database itself.
        Index(
            "uq_models_single_default",
            "workspace_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    provider: str = Field(nullable=False)
    model_id: str = Field(nullable=False)
    is_enabled: bool = Field(default=True, nullable=False)
    # The workspace default model (unset allowed — consumers fall back to the
    # first available model). Only meaningful on an enabled row: disabling a
    # model clears its flag.
    is_default: bool = Field(default=False, nullable=False)


class ModelProviderCredentialDB(BaseDBModel, table=True):
    """One encrypted workspace-level API key per model provider."""

    __tablename__ = "model_provider_credentials"

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            name="uq_model_credentials_workspace_provider",
        ),
    )

    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    provider: str = Field(nullable=False, index=True)
    api_key_encrypted: str = Field(sa_column=Column(Text, nullable=False))
