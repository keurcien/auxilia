import os
from fastapi import APIRouter
from app.model_providers.models import ModelProviderRead, ModelProviderType

router = APIRouter(prefix="/model-providers", tags=["model-providers"])

@router.get("/", response_model=list[ModelProviderRead])
async def get_model_providers() -> list[ModelProviderRead]:
    """List all model providers."""
    model_providers = []
    if os.getenv("OPENAI_API_KEY"):
        model_providers.append(ModelProviderRead(name=ModelProviderType.openai))
    if os.getenv("DEEPSEEK_API_KEY"):
        model_providers.append(ModelProviderRead(name=ModelProviderType.deepseek))
    if os.getenv("ANTHROPIC_API_KEY"):
        model_providers.append(ModelProviderRead(name=ModelProviderType.anthropic))
    if os.getenv("GOOGLE_API_KEY"):
        model_providers.append(ModelProviderRead(name=ModelProviderType.google))
    
    return list(model_providers)