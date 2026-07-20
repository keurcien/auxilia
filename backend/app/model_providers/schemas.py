from datetime import datetime

from pydantic import BaseModel
from sqlmodel import SQLModel

from app.model_providers.models import ModelProviderType


class ModelProviderResponse(SQLModel):
    name: ModelProviderType


class ModelResponse(BaseModel):
    name: str
    id: str
    chef: str
    chefSlug: str
    providers: list[ModelProviderType]


class ModelCreateDB(SQLModel):
    """Server-side create payload for an enablement row (timestamps are
    server-generated — passing a full ModelDB through BaseRepository.create
    would fail validation on its None timestamps)."""

    provider: str
    model_id: str
    is_enabled: bool


class ManagedModelResponse(BaseModel):
    """One row of the admin Settings view: a whitelist model (with its
    enablement state) or an orphan enablement row flagged deprecated."""

    provider: str
    model_id: str
    display_name: str
    chef: str
    chef_slug: str
    multimodal: bool = False
    supports_structured_output: bool = False
    is_enabled: bool
    deprecated: bool = False


class ModelEnabledUpdate(BaseModel):
    is_enabled: bool


class WhitelistSyncResponse(BaseModel):
    added: list[str]
    removed: list[str]
    model_count: int
    fetched_at: datetime
