from enum import Enum

from sqlalchemy import Index, text
from sqlmodel import Field, UniqueConstraint

from app.models import BaseDBModel


class ModelProviderType(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    anthropic = "anthropic"
    google = "google"
    ollama = "ollama"
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
        UniqueConstraint("provider", "model_id"),
        # At most one workspace default, enforced by the database itself.
        Index(
            "uq_models_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    provider: str = Field(nullable=False)
    model_id: str = Field(nullable=False)
    is_enabled: bool = Field(default=True, nullable=False)
    # The workspace default model (unset allowed — consumers fall back to the
    # first available model). Only meaningful on an enabled row: disabling a
    # model clears its flag.
    is_default: bool = Field(default=False, nullable=False)
