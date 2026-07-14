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


# Models that require adaptive thinking (`{"type": "adaptive"}` + `effort`).
# Opus 4.7+ dropped manual extended thinking and return a 400 for the legacy
# `{"type": "enabled", "budget_tokens": ...}` format. Everything else uses
# the legacy `enabled` format.
ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset(
    {"claude-opus-4-6", "claude-opus-4-8", "claude-sonnet-5"}
)

# Providers whose API only accepts tool_choice="auto" (no "required" / named
# function). Structured output formats via provider-native json_schema
# (ProviderStrategy) on these instead of a forced tool call — Meta's Model API
# rejects forced tool_choice with a 400. See DeferredStructuredOutputMiddleware.
AUTO_ONLY_TOOL_CHOICE_PROVIDERS: frozenset[str] = frozenset({"meta"})

# OpenRouter catalog: our model id -> (OpenRouter slug, GLM `reasoning_effort`).
# GLM 5.2 exposes two thinking levels; "max" is its deep-reasoning default, "high"
# is lighter. Each is surfaced to users as its own model.
OPENROUTER_MODELS: dict[str, tuple[str, str]] = {
    "glm-5.2-max": ("z-ai/glm-5.2", "max"),
    "glm-5.2-high": ("z-ai/glm-5.2", "high"),
}

LLM_PROVIDERS: list[ModelProvider] = []
MODELS: list[Model] = []

if model_provider_settings.openai_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(name="openai", api_key=model_provider_settings.openai_api_key)
    )
    MODELS.append(Model(name="gpt-4o-mini", provider="openai"))

if model_provider_settings.deepseek_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(name="deepseek", api_key=model_provider_settings.deepseek_api_key)
    )
    MODELS.append(Model(name="deepseek-v4-flash", provider="deepseek"))
    MODELS.append(Model(name="deepseek-v4-pro", provider="deepseek"))

if model_provider_settings.anthropic_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(
            name="anthropic", api_key=model_provider_settings.anthropic_api_key
        )
    )
    MODELS.append(Model(name="claude-haiku-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-sonnet-4-6", provider="anthropic"))
    MODELS.append(Model(name="claude-sonnet-5", provider="anthropic"))
    # Claude Opus temporarily disabled.
    # MODELS.append(Model(name="claude-opus-4-6", provider="anthropic"))
    # MODELS.append(Model(name="claude-opus-4-8", provider="anthropic"))

if model_provider_settings.google_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(name="google", api_key=model_provider_settings.google_api_key)
    )
    MODELS.append(Model(name="gemini-3-flash-preview", provider="google"))
    MODELS.append(Model(name="gemini-3-pro-preview", provider="google"))

if model_provider_settings.xiaomi_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(name="xiaomi", api_key=model_provider_settings.xiaomi_api_key)
    )
    MODELS.append(Model(name="mimo-v2.5-pro", provider="xiaomi"))
    MODELS.append(Model(name="mimo-v2.5", provider="xiaomi"))

if model_provider_settings.metaai_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(name="meta", api_key=model_provider_settings.metaai_api_key)
    )
    MODELS.append(Model(name="muse-spark-1.1", provider="meta"))

if model_provider_settings.openrouter_api_key:
    LLM_PROVIDERS.append(
        ModelProvider(
            name="openrouter", api_key=model_provider_settings.openrouter_api_key
        )
    )
    for _cid in OPENROUTER_MODELS:
        MODELS.append(Model(name=_cid, provider="openrouter"))


class ChatModelFactory:
    def create(self, provider: str, model_id: str, api_key: str):
        match provider:
            case "openai":
                return ChatOpenAI(model=model_id, api_key=api_key)
            case "deepseek":
                return ChatDeepSeek(
                    model=model_id,
                    api_key=api_key,
                    extra_body={"thinking": {"type": "disabled"}},
                )
            case "anthropic":
                kwargs: dict = {}
                if model_id in ADAPTIVE_THINKING_MODELS:
                    # `display` defaults to "omitted" on Opus 4.7+, which returns
                    # thinking blocks with an empty `thinking` field. langchain
                    # then drops the field when round-tripping the block after a
                    # tool call, and the API rejects it with
                    # `content.0.thinking.thinking: Field required`. Requesting
                    # "summarized" keeps the field populated so it survives the
                    # round-trip (and surfaces reasoning to the UI).
                    kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
                    kwargs["effort"] = "medium"
                else:
                    kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}
                return ChatAnthropic(
                    model=model_id,
                    temperature=1,
                    max_tokens=32768,
                    streaming=True,
                    timeout=None,
                    max_retries=2,
                    api_key=api_key,
                    **kwargs,
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
            case "xiaomi":
                return ChatOpenAI(
                    base_url="https://api.xiaomimimo.com/v1",
                    model=model_id,
                    api_key=api_key,
                )
            case "openrouter":
                # OpenAI-compatible gateway. Our model id encodes the GLM thinking
                # level; pass GLM's native `reasoning_effort` ("high"/"max"). Output
                # is capped generously (GLM 5.2 max = 32768) since "max" reasoning
                # produces long chains of thought.
                slug, effort = OPENROUTER_MODELS[model_id]
                return ChatOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    model=slug,
                    api_key=api_key,
                    max_tokens=32768,
                    extra_body={"reasoning_effort": effort},
                )
            case "meta":
                # Meta Model API — OpenAI-compatible Chat Completions.
                # ponytail: minimal config; add reasoning_effort / max_tokens
                # only if Muse Spark reasoning output needs tuning.
                return ChatOpenAI(
                    base_url="https://api.meta.ai/v1",
                    model=model_id,
                    api_key=api_key,
                )
            case _:
                raise ValueError(f"Provider {provider} not supported")
