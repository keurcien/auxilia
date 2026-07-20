from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.model_providers.catalog import provider_api_keys
from app.model_providers.models import ModelProviderType
from app.model_providers.schemas import (
    ManagedModelResponse,
    ModelEnabledUpdate,
    ModelProviderResponse,
    ModelResponse,
    WhitelistSyncResponse,
)
from app.model_providers.service import ModelService, get_model_service
from app.users.models import UserDB


router = APIRouter(prefix="/model-providers", tags=["model-providers"])


@router.get("/", response_model=list[ModelProviderResponse])
async def get_model_providers() -> list[ModelProviderResponse]:
    """List all model providers with a configured API key."""
    return [
        ModelProviderResponse(name=ModelProviderType(name))
        for name in provider_api_keys()
    ]


@router.get("/models", response_model=list[ModelResponse])
async def get_models(
    service: ModelService = Depends(get_model_service),
) -> list[ModelResponse]:
    """The model picker source: whitelist ∧ provider key ∧ admin-enabled."""
    return [
        ModelResponse(
            name=m.display_name,
            id=m.model_id,
            chef=m.chef,
            chefSlug=m.chef_slug,
            providers=[ModelProviderType(m.provider)],
        )
        for m in await service.list_available()
    ]


@router.get("/models/manage", response_model=list[ManagedModelResponse])
async def list_managed_models(
    _: UserDB = Depends(require_admin),  # side-effect auth check
    service: ModelService = Depends(get_model_service),
) -> list[ManagedModelResponse]:
    """Admin Settings view: every offerable model with its enablement state."""
    return await service.list_manage()


@router.put("/models/{provider}/{model_id:path}", response_model=ManagedModelResponse)
async def set_model_enabled(
    provider: str,
    model_id: str,
    update: ModelEnabledUpdate,
    _: UserDB = Depends(require_admin),  # side-effect auth check
    service: ModelService = Depends(get_model_service),
) -> ManagedModelResponse:
    return await service.set_enabled(provider, model_id, update.is_enabled)


@router.post("/whitelist/sync", response_model=WhitelistSyncResponse)
async def sync_model_whitelist(
    _: UserDB = Depends(require_admin),  # side-effect auth check
    service: ModelService = Depends(get_model_service),
) -> WhitelistSyncResponse:
    """Force-fetch the CDN whitelist now. Raises 400 (instead of silently
    falling back) when the fetch or validation fails — the admin pressed the
    button and needs to know."""
    return await service.sync()
