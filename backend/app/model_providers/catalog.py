from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.model_providers.settings import model_provider_settings


class ModelProvider(BaseModel):
    name: str
    api_key: str


class Model(BaseModel):
    name: str
    provider: str


LLM_PROVIDERS: list[ModelProvider] = []
MODELS: list[Model] = []

if model_provider_settings.openai_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="openai", api_key=model_provider_settings.openai_api_key))
    MODELS.append(Model(name="gpt-4o-mini", provider="openai"))

if model_provider_settings.deepseek_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="deepseek", api_key=model_provider_settings.deepseek_api_key))
    MODELS.append(Model(name="deepseek-v4-flash", provider="deepseek"))
    MODELS.append(Model(name="deepseek-v4-pro", provider="deepseek"))
    MODELS.append(Model(name="deepseek-chat", provider="deepseek"))
    MODELS.append(Model(name="deepseek-reasoner", provider="deepseek"))

if model_provider_settings.anthropic_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="anthropic", api_key=model_provider_settings.anthropic_api_key))
    MODELS.append(Model(name="claude-haiku-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-sonnet-4-6", provider="anthropic"))
    MODELS.append(Model(name="claude-opus-4-6", provider="anthropic"))

if model_provider_settings.google_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="google", api_key=model_provider_settings.google_api_key))
    MODELS.append(Model(name="gemini-3-flash-preview", provider="google"))
    MODELS.append(Model(name="gemini-3-pro-preview", provider="google"))


class ChatModelFactory:

    def create(self, provider: str, model_id: str, api_key: str):
        match provider:
            case "openai":
                return ChatOpenAI(model=model_id, api_key=api_key)
            case "deepseek":
                return ChatDeepSeek(model=model_id, api_key=api_key, extra_body={"thinking": {"type": "disabled"}})
            case "anthropic":
                return ChatAnthropic(
                    model=model_id,
                    temperature=1,
                    max_tokens=2048,
                    streaming=True,
                    timeout=None,
                    thinking={"type": "enabled", "budget_tokens": 1024},
                    max_retries=2,
                    api_key=api_key,
                )
            case "google":
                return ChatGoogleGenerativeAI(
                    model=model_id,
                    temperature=0,
                    max_tokens=None,
                    timeout=None,
                    max_retries=2,
                    streaming=True,
                    include_thoughts=True,
                    thinking_budget=-1,
                    api_key=api_key,
                )
            case _:
                raise ValueError(f"Provider {provider} not supported")
