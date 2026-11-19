from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field
from sqlmodel import SQLModel

from app.model_providers.models import ModelProviderType
from app.model_providers.pricing import TokenPrices


class ModelProviderResponse(SQLModel):
    name: ModelProviderType


class ProviderCredentialSource(str, Enum):
    database = "database"
    environment = "environment"
    adc = "adc"
    none = "none"


class ProviderConfigurationType(str, Enum):
    api_key = "api_key"
    base_url = "base_url"


class ModelProviderConfigResponse(BaseModel):
    name: ModelProviderType
    is_configured: bool
    source: ProviderCredentialSource
    configuration_type: ProviderConfigurationType = ProviderConfigurationType.api_key
    base_url: str | None = None
    last4: str | None = None
    key_length: int | None = None


class ModelProviderAPIKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


class OllamaConnectionUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=2048)


class OllamaDiscoveryResponse(BaseModel):
    config: ModelProviderConfigResponse
    discovered_count: int
    available_count: int


class ModelResponse(BaseModel):
    prices: TokenPrices | None = None
    name: str
    id: str
    chef: str
    chefSlug: str
    providers: list[ModelProviderType]
    # The *effective* workspace default (admin-flagged model when available,
    # else the first available one) — pickers preselect this row.
    isDefault: bool = False
    # Whether the model accepts non-text input on our serving path — the
    # composer gates attachments on this (per model, not per chef: e.g. GLM
    # 5.3 Flash takes images while plain GLM 5.3 does not).
    multimodal: bool = False
    # Maximum input tokens, None when the catalog doesn't know it.
    contextWindow: int | None = None
    # The reasoning-effort values the user may pick for this model (empty =
    # no effort knob) and the level in effect when they pick nothing (None =
    # provider-managed/dynamic, shown as Auto).
    reasoningEffortLevels: list[str] = []
    reasoningEffortDefault: str | None = None


class ModelCreateDB(SQLModel):
    """Server-side create payload for an enablement row (timestamps are
    server-generated — passing a full ModelDB through BaseRepository.create
    would fail validation on its None timestamps)."""

    workspace_id: UUID
    provider: str
    model_id: str
    is_enabled: bool


class ManagedModelResponse(BaseModel):
    """One row of the admin Settings view: a whitelist model (with its
    enablement state) or an orphan enablement row flagged deprecated."""

    prices: TokenPrices | None = None
    provider: str
    model_id: str
    display_name: str
    chef: str
    chef_slug: str
    multimodal: bool = False
    supports_structured_output: bool = False
    supports_tools: bool = True
    is_available: bool = True
    is_enabled: bool
    # The explicit admin choice only — no fallback here, so the Settings UI
    # shows an unset default as unset.
    is_default: bool = False
    # The workspace quick model (explicit admin choice, unset shown as unset):
    # used for the runtime's short intermediate calls such as the lazy
    # tool-discovery router.
    is_quick: bool = False
    deprecated: bool = False


class ModelEnabledUpdate(BaseModel):
    is_enabled: bool


class ModelDefaultUpdate(BaseModel):
    """Body of PUT /models/default and PUT /models/quick — which model takes
    the role."""

    provider: str
    model_id: str


class WhitelistSyncResponse(BaseModel):
    added: list[str]
    removed: list[str]
    model_count: int
    fetched_at: datetime
