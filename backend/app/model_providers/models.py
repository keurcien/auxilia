from enum import Enum

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
    __table_args__ = (UniqueConstraint("provider", "model_id"),)

    provider: str = Field(nullable=False)
    model_id: str = Field(nullable=False)
    is_enabled: bool = Field(default=True, nullable=False)
