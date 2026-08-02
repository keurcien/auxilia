"""Remote reference catalogs — a curated list that lives in a CDN file.

auxilia keeps two of these: the model whitelist (which models we can offer) and
the official MCP server catalog (which servers appear in the "add server"
dialog). Both are hand-editable YAML behind a CDN so extending them needs no
migration and no release, and both are read through the same four layers,
freshest first:

1. a per-process memo (short, so an admin sync converges everywhere in a minute)
2. Redis (``<prefix>``, 7-day TTL, shared by every instance)
3. the CDN file itself (validated all-or-nothing; a bad file is ignored)
4. ``<prefix>:last_good`` (no TTL — the last file that validated)
5. the bundled snapshot shipped with the backend

The long TTL makes propagation admin-driven: editing the CDN file does nothing
until an admin hits the sync endpoint, which force-fetches, raises on failure
instead of falling back, and returns the diff. The CDN is never on a request hot
path in a way that can take the app down.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel
from redis.asyncio import Redis

from app.redis_client import get_redis


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

TTL_SECONDS = 7 * 24 * 60 * 60
MEMO_TTL_SECONDS = 60
FETCH_TIMEOUT_SECONDS = 10
LOCK_TTL_SECONDS = 30


class SyncResult(BaseModel):
    """What changed in an admin-triggered force-fetch. ``added``/``removed`` hold
    each entry's identity key (a model_id, a server url)."""

    added: list[str]
    removed: list[str]
    count: int
    fetched_at: datetime


class RemoteCatalog(Generic[T]):
    """One CDN-backed catalog. Callers supply the parsing and identity rules;
    this owns the caching, fallback and sync mechanics.

    ``url`` is a callable, not a string, so the setting is read at call time
    (settings objects are module-level singletons, but tests and env reloads
    shouldn't be baked into a catalog built at import time).
    """

    def __init__(
        self,
        *,
        prefix: str,
        item_model: type[T],
        parse: Callable[[str], list[T]],
        key: Callable[[T], str],
        url: Callable[[], str | None],
        bundled_path: Path,
        ttl_seconds: int = TTL_SECONDS,
        memo_ttl_seconds: int = MEMO_TTL_SECONDS,
    ) -> None:
        self.prefix = prefix
        self.cache_key = prefix
        self.last_good_key = f"{prefix}:last_good"
        self.meta_key = f"{prefix}:meta"
        self.lock_key = f"{prefix}:lock"
        self._item_model = item_model
        self._parse = parse
        self._key = key
        self._url = url
        self._bundled_path = bundled_path
        self._ttl_seconds = ttl_seconds
        self._memo_ttl_seconds = memo_ttl_seconds
        self._memo: tuple[float, list[T]] | None = None

    @property
    def url(self) -> str | None:
        return self._url()

    def bundled(self) -> list[T]:
        """The snapshot shipped with the backend — the fallback of last resort."""
        return self._parse(self._bundled_path.read_text(encoding="utf-8"))

    def invalidate_memo(self) -> None:
        self._memo = None

    def _dumps(self, items: list[T]) -> str:
        return json.dumps([item.model_dump(mode="json") for item in items])

    def _loads(self, payload: str) -> list[T]:
        return [self._item_model.model_validate(item) for item in json.loads(payload)]

    async def _store(self, redis: Redis, items: list[T], etag: str | None) -> None:
        payload = self._dumps(items)
        meta = json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "etag": etag,
                "count": len(items),
            }
        )
        async with redis.pipeline(transaction=True) as pipe:
            pipe.set(self.cache_key, payload, ex=self._ttl_seconds)
            pipe.set(self.last_good_key, payload)
            pipe.set(self.meta_key, meta)
            await pipe.execute()

    async def _fetch(self, url: str) -> tuple[list[T], str | None]:
        """GET + validate the CDN file. Raises on any failure."""
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        response.raise_for_status()
        return self._parse(response.text), response.headers.get("etag")

    async def _refresh(self, redis: Redis, url: str) -> list[T] | None:
        """Cache-miss path: fetch behind a single-flight lock. Returns None when
        the fetch fails or another instance holds the lock — callers fall back."""
        if not await redis.set(self.lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS):
            return None
        try:
            items, etag = await self._fetch(url)
            await self._store(redis, items, etag)
            return items
        except Exception:
            logger.warning(
                "%s refresh from %s failed; falling back",
                self.prefix,
                url,
                exc_info=True,
            )
            return None
        finally:
            await redis.delete(self.lock_key)

    async def get(self) -> list[T]:
        """The current catalog, through memo → Redis → CDN → last_good → bundled."""
        if (
            self._memo is not None
            and monotonic() - self._memo[0] < self._memo_ttl_seconds
        ):
            return self._memo[1]

        redis = get_redis()
        items: list[T] | None = None
        try:
            cached = await redis.get(self.cache_key)
            if cached:
                items = self._loads(cached)
            else:
                url = self.url
                if url:
                    items = await self._refresh(redis, url)
                if items is None:
                    last_good = await redis.get(self.last_good_key)
                    if last_good:
                        items = self._loads(last_good)
        except Exception:
            logger.warning(
                "%s read from Redis failed; using bundled snapshot",
                self.prefix,
                exc_info=True,
            )

        if items is None:
            items = self.bundled()
        self._memo = (monotonic(), items)
        return items

    async def sync(self) -> SyncResult:
        """Admin-triggered refresh: force-fetch, validate, overwrite the cache.

        Unlike ``get`` this RAISES on failure (the admin pressed the button; they
        need to know) and returns the diff vs the previously served list. Callers
        translate ``ValueError`` / ``httpx.HTTPError`` into a domain exception.
        """
        url = self.url
        if url is None:
            raise ValueError("no catalog URL configured")
        previous = await self.get()
        items, etag = await self._fetch(url)

        await self._store(get_redis(), items, etag)
        self.invalidate_memo()

        previous_keys = {self._key(item) for item in previous}
        current_keys = {self._key(item) for item in items}
        return SyncResult(
            added=sorted(current_keys - previous_keys),
            removed=sorted(previous_keys - current_keys),
            count=len(items),
            fetched_at=datetime.now(UTC),
        )
