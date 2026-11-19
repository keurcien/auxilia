"""The auxilia model whitelist — the curated list of models we can offer.

The canonical file is external (a hand-editable YAML behind a CDN,
``MODEL_WHITELIST_URL``) so adding a model doesn't require a release. Caching,
fallback and admin-sync mechanics live in ``app.utils.remote_catalog``; this
module owns only what is model-specific: the entry shape, the validation rules,
and the bundled snapshot.
"""

from pathlib import Path
from typing import Literal, get_args

import httpx
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from app.exceptions import DomainValidationError
from app.model_providers.pricing import TokenPrices
from app.model_providers.settings import model_provider_settings
from app.model_providers.web_search import NATIVE_WEB_SEARCH_PROVIDERS
from app.utils.remote_catalog import RemoteCatalog


# Providers ChatModelFactory can drive. A whitelist entry with any other
# provider is a data-entry error and fails validation (all-or-nothing).
SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "deepseek",
        "anthropic",
        "google",
        "xiaomi",
        "openrouter",
        "meta",
        "ollama",
    }
)

# The canonical reasoning-effort ladder (the industry superset, ordered from
# least to most reasoning). Whitelist entries declare the per-model subset —
# no two providers accept the same one, and sending an undeclared value is
# never safe (some providers coerce silently, others 400). "none" in a
# model's levels means its thinking can be turned off entirely.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

# Provider-verified upper bounds for every effort-enabled model in the bundled
# catalog. A remote catalog may expose a narrower subset, but it cannot add a
# value the serving endpoint rejects. Unknown/new models still go through the
# canonical-ladder validation below until their provider matrix is audited.
KNOWN_REASONING_EFFORT_LEVELS: dict[str, frozenset[ReasoningEffort]] = {
    "gpt-5": frozenset({"minimal", "low", "medium", "high"}),
    "gpt-5-mini": frozenset({"minimal", "low", "medium", "high"}),
    "gpt-5-nano": frozenset({"minimal", "low", "medium", "high"}),
    "gpt-5.1": frozenset({"none", "low", "medium", "high"}),
    "gpt-5.2": frozenset({"none", "low", "medium", "high", "xhigh"}),
    "gpt-5.4": frozenset({"none", "low", "medium", "high", "xhigh"}),
    "gpt-5.5": frozenset({"none", "low", "medium", "high", "xhigh"}),
    "gpt-5.6-luna": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-5.6-sol": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-5.6-terra": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-luna": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-sol": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6.1-sol": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "gpt-6.1-terra": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-astra": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "gpt-6.2-sol": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "gpt-6.2-astra": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-fable-5-1": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-haiku-5-5": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-sonnet-4-6": frozenset({"low", "medium", "high", "max"}),
    "claude-sonnet-5": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-sonnet-5-5": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-opus-4-6": frozenset({"low", "medium", "high", "max"}),
    "claude-opus-4-8": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-opus-5": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "claude-opus-5-5": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "deepseek-v4-flash": frozenset({"none", "low", "high", "max"}),
    "deepseek-v4-flash-vision-exp": frozenset({"none", "low", "high", "max"}),
    "deepseek-flash": frozenset({"none", "low", "high", "max"}),
    "deepseek-v4-pro": frozenset({"none", "low", "high", "max"}),
    "gemini-3-flash-preview": frozenset({"minimal", "low", "medium", "high"}),
    "gemini-3.1-pro-preview": frozenset({"low", "medium", "high"}),
    "gemini-3.5-flash": frozenset({"minimal", "low", "medium", "high"}),
    "gemini-3.5-flash-lite": frozenset({"minimal", "low", "medium", "high"}),
    "gemini-3.6-flash": frozenset({"minimal", "low", "medium", "high"}),
    "gemini-3.7-flash": frozenset({"low", "medium", "high"}),
    "gemini-3.8-flash": frozenset({"low", "medium", "high"}),
    "gemini-4-argon": frozenset({"low", "medium", "high"}),
    "muse-spark-1.2": frozenset({"minimal", "low", "medium", "high", "xhigh"}),
    "muse-spark-1.3": frozenset({"minimal", "low", "medium", "high", "xhigh", "max"}),
    "muse-wonder-1.0": frozenset({"minimal", "low", "medium", "high", "xhigh", "max"}),
    "z-ai/glm-5.2": frozenset({"high", "max"}),
    "z-ai/glm-5.3": frozenset({"low", "high", "max"}),
    "z-ai/glm-5.3-flash": frozenset({"low", "high", "max"}),
    "z-ai/glm-5.3-prime": frozenset({"low", "high", "max"}),
    "z-ai/glm-5.3-flashx": frozenset({"low", "high", "max"}),
    "z-ai/glm-5.3-flashx-legal": frozenset({"low", "high", "max"}),
    "qwen/qwen3.8-max-0902": frozenset({"low", "medium", "xhigh"}),
    "qwen/qwen3.8-max-prime": frozenset({"low", "medium", "xhigh"}),
    "qwen/qwen3.8-27b": frozenset({"low", "medium", "xhigh"}),
    "qwen/qwen3.8-flash": frozenset({"low", "medium", "xhigh"}),
    "qwen/qwen3.8-omni-flash": frozenset({"low", "medium", "xhigh"}),
    "qwen/qwen3.8-2.4t-a95b": frozenset({"low", "medium", "xhigh"}),
}

# The single copy of the whitelist: bundled into the image as the offline
# fallback and uploaded as-is to the CDN (`MODEL_WHITELIST_URL`).
_BUNDLED_PATH = Path(__file__).parent / "whitelist.yaml"


class SupportedModel(BaseModel):
    # Optional for compatibility with older remote catalogs. Missing means
    # unknown, never free; supplied pricing requires all core token rates.
    prices: TokenPrices | None = None
    provider: str
    model_id: str
    # Normally identical to model_id. Workspace-discovered providers namespace
    # the persisted id while sending this provider-native value at runtime.
    runtime_model_id: str | None = None
    display_name: str
    # Model creator shown in the picker (logo lookup by slug). Defaults to the
    # provider; only differs when the creator isn't the serving provider
    # (e.g. Z.ai models served through OpenRouter).
    chef: str | None = None
    chef_slug: str | None = None
    multimodal: bool = False
    # Maximum input tokens the serving endpoint accepts. None = unknown: the
    # runtime falls back to the langchain model profile, and the composer's
    # context gauge shows absolute counts without a percentage.
    context_window: int | None = Field(default=None, gt=0)
    supports_structured_output: bool = False
    supports_tools: bool = True
    is_available: bool = True
    # Provider-native schema discovery (`tool_search`). False means the runtime
    # uses its model-driven fallback when an agent enables tool discovery.
    supports_tool_search: bool = False
    # None keeps older remote catalogs compatible: providers whose native
    # serving path supports server-side search inherit True. An entry may set
    # False explicitly if one model on such a provider does not support it.
    supports_web_search: bool | None = None
    # The reasoning-effort values a user may pick for this model (empty =
    # no effort knob, the picker doesn't render one). Values must be what the
    # serving endpoint actually accepts — silent coercion tiers don't count.
    reasoning_effort_levels: list[ReasoningEffort] = []
    # APPLIED when the user picks nothing: ensure_available resolves a NULL
    # thread/trigger effort to this level, so editing it in the CDN file
    # changes what unset means workspace-wide (explicit choices are never
    # touched). None with non-empty levels = provider-managed/dynamic — the
    # factory sends no effort at all and keeps its historical default path.
    reasoning_effort_default: ReasoningEffort | None = None

    @field_validator("provider")
    @classmethod
    def provider_must_be_supported(cls, v: str) -> str:
        if v not in SUPPORTED_PROVIDERS:
            raise ValueError(f"provider {v!r} is not supported by ChatModelFactory")
        return v

    @model_validator(mode="after")
    def default_chef_from_provider(self) -> "SupportedModel":
        if self.chef is None:
            self.chef = self.provider.capitalize()
        if self.chef_slug is None:
            self.chef_slug = self.provider
        if self.supports_web_search is None:
            self.supports_web_search = self.provider in NATIVE_WEB_SEARCH_PROVIDERS
        return self

    @model_validator(mode="after")
    def reasoning_effort_is_coherent(self) -> "SupportedModel":
        ladder = get_args(ReasoningEffort)
        allowed = KNOWN_REASONING_EFFORT_LEVELS.get(self.model_id)
        unsupported = (
            set() if allowed is None else set(self.reasoning_effort_levels) - allowed
        )
        if allowed is not None and unsupported:
            raise ValueError(
                f"model {self.model_id!r} declares unsupported reasoning effort "
                f"levels: {', '.join(sorted(unsupported))} "
                f"(accepted: {', '.join(level for level in ladder if level in allowed)})"
            )
        if len(set(self.reasoning_effort_levels)) != len(self.reasoning_effort_levels):
            raise ValueError(
                f"model {self.model_id!r} has duplicate reasoning_effort_levels"
            )
        # Levels must follow the canonical ladder order — the picker renders
        # the list as-is, so an out-of-order file would show `high` above
        # `low`. Reject it like any other data-entry error.
        positions = [ladder.index(level) for level in self.reasoning_effort_levels]
        if positions != sorted(positions):
            raise ValueError(
                f"model {self.model_id!r} has out-of-order reasoning_effort_levels "
                f"(expected the ladder order {', '.join(ladder)})"
            )
        if (
            self.reasoning_effort_default is not None
            and self.reasoning_effort_default not in self.reasoning_effort_levels
        ):
            raise ValueError(
                f"model {self.model_id!r}: reasoning_effort_default "
                f"{self.reasoning_effort_default!r} is not in reasoning_effort_levels"
            )
        return self


class WhitelistDocument(BaseModel):
    schema_version: Literal[1]
    models: list[SupportedModel]

    @model_validator(mode="after")
    def models_non_empty_and_unique(self) -> "WhitelistDocument":
        if not self.models:
            raise ValueError("whitelist has no models")
        # model_id must be unique across providers: threads store the bare
        # model_id, so it is the lookup key.
        seen: set[str] = set()
        for m in self.models:
            if m.model_id in seen:
                raise ValueError(f"duplicate model_id {m.model_id!r}")
            seen.add(m.model_id)
        return self


def parse_whitelist(text: str) -> list[SupportedModel]:
    """Parse + validate a whitelist YAML. Raises ValueError on any problem —
    callers treat the file as all-or-nothing."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"whitelist is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("whitelist root must be a mapping")
    return WhitelistDocument.model_validate(data).models


_catalog: RemoteCatalog[SupportedModel] = RemoteCatalog(
    prefix="models:whitelist",
    item_model=SupportedModel,
    parse=parse_whitelist,
    key=lambda m: m.model_id,
    url=lambda: model_provider_settings.model_whitelist_url,
    bundled_path=_BUNDLED_PATH,
)


def bundled_whitelist() -> list[SupportedModel]:
    """The snapshot shipped with the backend — the fallback of last resort."""
    return _catalog.bundled()


async def get_whitelist() -> list[SupportedModel]:
    """The current whitelist, through memo → Redis → CDN → last_good → bundled."""
    return await _catalog.get()


async def sync_whitelist() -> dict:
    """Admin-triggered refresh: force-fetch, validate, overwrite the cache.

    Unlike the lazy path this RAISES on failure (the admin pressed the button;
    they need to know) and returns the diff vs the previously served list.
    """
    if not _catalog.url:
        raise DomainValidationError(
            "No MODEL_WHITELIST_URL configured; this deployment uses the bundled whitelist."
        )
    try:
        result = await _catalog.sync()
    except ValueError as exc:
        raise DomainValidationError(f"Whitelist file is invalid: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DomainValidationError(f"Whitelist fetch failed: {exc}") from exc

    return {
        "added": result.added,
        "removed": result.removed,
        "model_count": result.count,
        "fetched_at": result.fetched_at,
    }
