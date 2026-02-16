import requests
from fastapi import APIRouter
from .settings import model_provider_settings
from app.model_providers.models import ModelProviderRead, ModelProviderType, ModelRead


router = APIRouter(prefix="/model-providers", tags=["model-providers"])


def get_litellm_models() -> list[dict]:
    response = requests.get(
        f"{model_provider_settings.litellm_api_base}/v1/models",
        headers={
            "Authorization": f"Bearer {model_provider_settings.litellm_api_key}",
            "Content-Type": "application/json"
        }
    )
    return response.json()["data"]


@router.get("/", response_model=list[ModelProviderRead])
async def get_model_providers() -> list[ModelProviderRead]:
    """List all model providers."""
    model_providers = []
    if model_provider_settings.openai_api_key:
        model_providers.append(ModelProviderRead(
            name=ModelProviderType.openai))
    if model_provider_settings.deepseek_api_key:
        model_providers.append(ModelProviderRead(
            name=ModelProviderType.deepseek))
    if model_provider_settings.anthropic_api_key:
        model_providers.append(ModelProviderRead(
            name=ModelProviderType.anthropic))
    if model_provider_settings.google_api_key:
        model_providers.append(ModelProviderRead(
            name=ModelProviderType.google))

    return list(model_providers)


@router.get("/models", response_model=list[ModelRead])
async def get_models() -> list[ModelRead]:
    """List all models available."""
    models = []
    if model_provider_settings.openai_api_key:
        models.extend([ModelRead(name="GPT-4o mini", providers=[ModelProviderType.openai],
                      id="gpt-4o-mini", chef="OpenAI", chefSlug="openai")])
    if model_provider_settings.deepseek_api_key:
        models.extend([
            ModelRead(name="DeepSeek Chat", providers=[
                      ModelProviderType.deepseek], id="deepseek-chat", chef="DeepSeek", chefSlug="deepseek"),
            ModelRead(name="DeepSeek Reasoner", providers=[
                      ModelProviderType.deepseek], id="deepseek-reasoner", chef="DeepSeek", chefSlug="deepseek"),
        ])
    if model_provider_settings.anthropic_api_key:
        models.extend([
            ModelRead(name="Claude Haiku 4.5", providers=[
                      ModelProviderType.anthropic], id="claude-haiku-4-5", chef="Anthropic", chefSlug="anthropic"),
            ModelRead(name="Claude Sonnet 4.5", providers=[
                      ModelProviderType.anthropic], id="claude-sonnet-4-5", chef="Anthropic", chefSlug="anthropic"),
            ModelRead(name="Claude Opus 4.5", providers=[
                      ModelProviderType.anthropic], id="claude-opus-4-5", chef="Anthropic", chefSlug="anthropic"),
        ])
    if model_provider_settings.google_api_key:
        models.extend([
            ModelRead(name="Gemini 3 Flash Preview", providers=[
                      ModelProviderType.google], id="gemini-3-flash-preview", chef="Google", chefSlug="google"),
            ModelRead(name="Gemini 3 Pro Preview", providers=[
                      ModelProviderType.google], id="gemini-3-pro-preview", chef="Google", chefSlug="google"),
        ])
    # if model_provider_settings.litellm_api_key:
    #     if not model_provider_settings.litellm_api_base:
    #         raise ValueError("LITELLM_API_BASE is not set")

    #     litellm_models = get_litellm_models()

    #     for model in litellm_models:
    #         _, model_id = model["id"].split("/")
    #         models.extend([
    #             ModelRead(name=model_id, providers=[ModelProviderType.litellm], id=model_id, chef="LiteLLM", chefSlug="litellm")
    #         ])

    return list(models)
