from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.model_providers.settings import model_provider_settings


# Models that require adaptive thinking (`{"type": "adaptive"}` + `effort`).
# Opus 4.7+ dropped manual extended thinking and return a 400 for the legacy
# `{"type": "enabled", "budget_tokens": ...}` format. Everything else uses
# the legacy `enabled` format.
ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset(
    {"claude-opus-4-6", "claude-opus-4-8", "claude-sonnet-5"}
)

# OpenAI reasoning models that reject function tools on /v1/chat/completions
# ("Function tools with reasoning_effort are not supported ... use /v1/responses
# or set reasoning_effort to 'none'"). Every agent binds tools, so route these
# through the Responses API, which supports tools + reasoning. Verified: the
# gpt-5.6 line needs this; gpt-5/5.1/5.2/5.4/5.5 work fine on chat completions.
OPENAI_RESPONSES_API_MODELS: frozenset[str] = frozenset(
    {"gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"}
)

# OpenRouter catalog: our model id -> (OpenRouter slug, GLM `reasoning_effort`).
# GLM 5.2 exposes two thinking levels; "max" is its deep-reasoning default, "high"
# is lighter. Each is surfaced to users as its own model.
OPENROUTER_MODELS: dict[str, tuple[str, str]] = {
    "glm-5.2-max": ("z-ai/glm-5.2", "max"),
    "glm-5.2-high": ("z-ai/glm-5.2", "high"),
}


def provider_api_keys() -> dict[str, str]:
    """Configured provider → API key, read at call time (not import time) so
    tests and env changes don't fight module state. Which *models* those
    providers may serve is decided by the whitelist + the workspace's
    enablement rows (ModelService), never here."""
    keys = {
        "openai": model_provider_settings.openai_api_key,
        "deepseek": model_provider_settings.deepseek_api_key,
        "anthropic": model_provider_settings.anthropic_api_key,
        "google": model_provider_settings.google_api_key,
        "xiaomi": model_provider_settings.xiaomi_api_key,
        "openrouter": model_provider_settings.openrouter_api_key,
        "meta": model_provider_settings.metaai_api_key,
    }
    return {name: key for name, key in keys.items() if key}


class ChatModelFactory:
    def create(self, provider: str, model_id: str, api_key: str):
        match provider:
            case "openai":
                # gpt-5.6 reasoning models require the Responses API to use
                # function tools (chat completions 400s); everything else is
                # fine on the default chat-completions path.
                return ChatOpenAI(
                    model=model_id,
                    api_key=api_key,
                    use_responses_api=model_id in OPENAI_RESPONSES_API_MODELS,
                )
            case "deepseek":
                # Reasoning enabled. max_tokens caps the answer so json_object
                # structured output isn't truncated mid-string (DeepSeek's JSON
                # mode guide warns about this); 32768 matches the other
                # reasoning providers here.
                return ChatDeepSeek(
                    model=model_id,
                    api_key=api_key,
                    max_tokens=32768,
                    extra_body={"thinking": {"type": "enabled"}},
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
