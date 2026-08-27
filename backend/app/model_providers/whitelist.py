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
from pydantic import BaseModel, field_validator, model_validator

from app.exceptions import DomainValidationError
from app.model_providers.settings import model_provider_settings
from app.utils.remote_catalog import RemoteCatalog


# Providers ChatModelFactory can drive. A whitelist entry with any other
# provider is a data-entry error and fails validation (all-or-nothing).
SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {"openai", "deepseek", "anthropic", "google", "xiaomi", "openrouter", "meta"}
)

# The canonical reasoning-effort ladder (the industry superset, ordered from
# least to most reasoning). Whitelist entries declare the per-model subset —
# no two providers accept the same one, and sending an undeclared value is
# never safe (some providers coerce silently, others 400). "none" in a
# model's levels means its thinking can be turned off entirely.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

_BUNDLED_PATH = Path(__file__).parent / "whitelist.yaml"


class SupportedModel(BaseModel):
    provider: str
    model_id: str
    display_name: str
    # Model creator shown in the picker (logo lookup by slug). Defaults to the
    # provider; only differs when the creator isn't the serving provider
    # (e.g. Z.ai models served through OpenRouter).
    chef: str | None = None
    chef_slug: str | None = None
    multimodal: bool = False
    supports_structured_output: bool = False
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
        return self

    @model_validator(mode="after")
    def reasoning_effort_is_coherent(self) -> "SupportedModel":
        if len(set(self.reasoning_effort_levels)) != len(self.reasoning_effort_levels):
            raise ValueError(
                f"model {self.model_id!r} has duplicate reasoning_effort_levels"
            )
        # Levels must follow the canonical ladder order — the picker renders
        # the list as-is, so an out-of-order file would show `high` above
        # `low`. Reject it like any other data-entry error.
        ladder = get_args(ReasoningEffort)
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
