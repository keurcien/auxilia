"""The auxilia model whitelist — the curated list of models we can offer.

The canonical file is external (a hand-editable YAML behind a CDN,
``MODEL_WHITELIST_URL``) so adding a model doesn't require a release. It is
read through three layers of fallback, freshest first:

1. Redis cache (``models:whitelist``, 7-day TTL, shared by all instances)
2. the CDN file itself (validated all-or-nothing; a bad file is ignored)
3. ``models:whitelist:last_good`` (no TTL — the last file that validated)
4. the bundled snapshot (``whitelist.yaml`` next to this module)

The long TTL makes propagation admin-driven: editing the CDN file does
nothing until an admin hits the sync endpoint (``sync_whitelist``), which
force-fetches, raises on failure instead of falling back, and returns the
diff. The CDN is never on the request hot path in a way that can take chat
down.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, field_validator, model_validator
from redis.asyncio import Redis

from app.exceptions import DomainValidationError
from app.model_providers.settings import model_provider_settings
from app.redis_client import get_redis


logger = logging.getLogger(__name__)

# Providers ChatModelFactory can drive. A whitelist entry with any other
# provider is a data-entry error and fails validation (all-or-nothing).
SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {"openai", "deepseek", "anthropic", "google", "xiaomi", "openrouter", "meta"}
)

WHITELIST_CACHE_KEY = "models:whitelist"
WHITELIST_LAST_GOOD_KEY = "models:whitelist:last_good"
WHITELIST_META_KEY = "models:whitelist:meta"
WHITELIST_LOCK_KEY = "models:whitelist:lock"
WHITELIST_TTL_SECONDS = 7 * 24 * 60 * 60
FETCH_TIMEOUT_SECONDS = 10

_BUNDLED_PATH = Path(__file__).parent / "whitelist.yaml"

# Per-process memo of the parsed models so the common path (Redis hit) doesn't
# re-parse JSON on every request. Short-lived so an admin sync converges
# everywhere within a minute.
_MEMO_TTL_SECONDS = 60
_memo: tuple[float, list["SupportedModel"]] | None = None


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


def bundled_whitelist() -> list[SupportedModel]:
    """The snapshot shipped with the backend — the fallback of last resort."""
    return parse_whitelist(_BUNDLED_PATH.read_text())


def _models_to_json(models: list[SupportedModel]) -> str:
    return json.dumps([m.model_dump() for m in models])


def _models_from_json(payload: str) -> list[SupportedModel]:
    return [SupportedModel.model_validate(m) for m in json.loads(payload)]


async def _store(redis: Redis, models: list[SupportedModel], etag: str | None) -> None:
    payload = _models_to_json(models)
    meta = json.dumps(
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "etag": etag,
            "model_count": len(models),
        }
    )
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(WHITELIST_CACHE_KEY, payload, ex=WHITELIST_TTL_SECONDS)
        pipe.set(WHITELIST_LAST_GOOD_KEY, payload)
        pipe.set(WHITELIST_META_KEY, meta)
        await pipe.execute()


async def _fetch(url: str) -> tuple[list[SupportedModel], str | None]:
    """GET + validate the CDN file. Raises on any failure."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
    response.raise_for_status()
    return parse_whitelist(response.text), response.headers.get("etag")


async def _refresh(redis: Redis, url: str) -> list[SupportedModel] | None:
    """Cache-miss path: fetch behind a single-flight lock. Returns None when
    the fetch fails or another instance holds the lock — callers fall back."""
    if not await redis.set(WHITELIST_LOCK_KEY, "1", nx=True, ex=30):
        return None
    try:
        models, etag = await _fetch(url)
        await _store(redis, models, etag)
        return models
    except Exception:
        logger.warning(
            "Whitelist refresh from %s failed; falling back", url, exc_info=True
        )
        return None
    finally:
        await redis.delete(WHITELIST_LOCK_KEY)


async def get_whitelist() -> list[SupportedModel]:
    """The current whitelist, through memo → Redis → CDN → last_good → bundled."""
    global _memo
    if _memo is not None and monotonic() - _memo[0] < _MEMO_TTL_SECONDS:
        return _memo[1]

    redis = get_redis()
    models: list[SupportedModel] | None = None
    try:
        cached = await redis.get(WHITELIST_CACHE_KEY)
        if cached:
            models = _models_from_json(cached)
        else:
            url = model_provider_settings.model_whitelist_url
            if url:
                models = await _refresh(redis, url)
            if models is None:
                last_good = await redis.get(WHITELIST_LAST_GOOD_KEY)
                if last_good:
                    models = _models_from_json(last_good)
    except Exception:
        logger.warning(
            "Whitelist read from Redis failed; using bundled snapshot", exc_info=True
        )

    if models is None:
        models = bundled_whitelist()
    _memo = (monotonic(), models)
    return models


async def sync_whitelist() -> dict:
    """Admin-triggered refresh: force-fetch, validate, overwrite the cache.

    Unlike the lazy path this RAISES on failure (the admin pressed the button;
    they need to know) and returns the diff vs the previously served list.
    """
    global _memo
    url = model_provider_settings.model_whitelist_url
    if not url:
        raise DomainValidationError(
            "No MODEL_WHITELIST_URL configured; this deployment uses the bundled whitelist."
        )
    previous = await get_whitelist()
    try:
        models, etag = await _fetch(url)
    except ValueError as exc:
        raise DomainValidationError(f"Whitelist file is invalid: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DomainValidationError(f"Whitelist fetch failed: {exc}") from exc

    redis = get_redis()
    await _store(redis, models, etag)
    _memo = None

    previous_ids = {m.model_id for m in previous}
    current_ids = {m.model_id for m in models}
    return {
        "added": sorted(current_ids - previous_ids),
        "removed": sorted(previous_ids - current_ids),
        "model_count": len(models),
        "fetched_at": datetime.now(UTC),
    }
