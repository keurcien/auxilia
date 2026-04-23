from fastapi import APIRouter

from app.model_providers.models import ModelProviderType
from app.model_providers.schemas import ModelProviderResponse, ModelResponse

from .settings import model_provider_settings


router = APIRouter(prefix="/model-providers", tags=["model-providers"])


@router.get("/", response_model=list[ModelProviderResponse])
async def get_model_providers() -> list[ModelProviderResponse]:
    """List all model providers."""
    model_providers = []
    if model_provider_settings.openai_api_key:
        model_providers.append(ModelProviderResponse(
            name=ModelProviderType.openai))
    if model_provider_settings.deepseek_api_key:
        model_providers.append(ModelProviderResponse(
            name=ModelProviderType.deepseek))
    if model_provider_settings.anthropic_api_key:
        model_providers.append(ModelProviderResponse(
            name=ModelProviderType.anthropic))
    if model_provider_settings.google_api_key:
        model_providers.append(ModelProviderResponse(
            name=ModelProviderType.google))

    return list(model_providers)


@router.get("/models", response_model=list[ModelResponse])
async def get_models() -> list[ModelResponse]:
    """List all models available."""
    models = []
    if model_provider_settings.openai_api_key:
        models.extend([ModelResponse(name="GPT-4o mini", providers=[ModelProviderType.openai],
                      id="gpt-4o-mini", chef="OpenAI", chefSlug="openai")])
    if model_provider_settings.deepseek_api_key:
        models.extend([
            ModelResponse(name="DeepSeek Chat", providers=[
                      ModelProviderType.deepseek], id="deepseek-chat", chef="DeepSeek", chefSlug="deepseek"),
            ModelResponse(name="DeepSeek Reasoner", providers=[
                      ModelProviderType.deepseek], id="deepseek-reasoner", chef="DeepSeek", chefSlug="deepseek"),
        ])
    if model_provider_settings.anthropic_api_key:
        models.extend([
            ModelResponse(name="Claude Haiku 4.5", providers=[
                      ModelProviderType.anthropic], id="claude-haiku-4-5", chef="Anthropic", chefSlug="anthropic"),
            ModelResponse(name="Claude Sonnet 4.6", providers=[
                      ModelProviderType.anthropic], id="claude-sonnet-4-6", chef="Anthropic", chefSlug="anthropic"),
            ModelResponse(name="Claude Opus 4.6", providers=[
                      ModelProviderType.anthropic], id="claude-opus-4-6", chef="Anthropic", chefSlug="anthropic"),
        ])
    if model_provider_settings.google_api_key:
        models.extend([
            ModelResponse(name="Gemini 3 Flash Preview", providers=[
                      ModelProviderType.google], id="gemini-3-flash-preview", chef="Google", chefSlug="google"),
            ModelResponse(name="Gemini 3 Pro Preview", providers=[
                      ModelProviderType.google], id="gemini-3-pro-preview", chef="Google", chefSlug="google"),
        ])

    return list(models)
