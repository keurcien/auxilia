"""Remote reference catalogs — a curated list that lives in a CDN file.

auxilia keeps two of these: the model whitelist (which models we can offer) and
the official MCP server catalog (which servers appear in the "add server"
dialog). Both are hand-editable YAML behind a CDN so extending them needs no
migration and no release, and both are read through the same five layers,
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

import contextlib
import hashlib
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
from redis.asyncio.lock import Lock
from redis.exceptions import LockError

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
        self._item_model = item_model
        self._parse = parse
        self._key = key
        self._url = url
        self._bundled_path = bundled_path
        self._ttl_seconds = ttl_seconds
        self._memo_ttl_seconds = memo_ttl_seconds
        # (stored_at, source_url, items) — the url is part of the memo identity
        # so changing the setting takes effect within a request, not a TTL.
        self._memo: tuple[float, str | None, list[T]] | None = None

    @property
    def url(self) -> str | None:
        return self._url()

    # Cache keys are scoped to the source URL so pointing a deployment at a
    # different file (or its own internal one) never serves another URL's
    # cached content; the old keys just age out of Redis.
    def _scope(self) -> str:
        digest = hashlib.sha256((self.url or "").encode()).hexdigest()[:12]
        return f"{self.prefix}:{digest}"

    @property
    def cache_key(self) -> str:
        return self._scope()

    @property
    def last_good_key(self) -> str:
        return f"{self._scope()}:last_good"

    @property
    def meta_key(self) -> str:
        return f"{self._scope()}:meta"

    @property
    def lock_key(self) -> str:
        return f"{self._scope()}:lock"

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

    def _lock(self, redis: Redis, *, blocking: bool) -> Lock:
        """Token-based lock shared by the lazy refresh and the admin sync, so a
        slow lazy fetch can never overwrite a fresher force-fetch. Tokens mean
        an owner whose lock expired can't delete a successor's lock."""
        return redis.lock(
            self.lock_key,
            timeout=LOCK_TTL_SECONDS,
            blocking=blocking,
            blocking_timeout=LOCK_TTL_SECONDS,
        )

    @staticmethod
    async def _release(lock: Lock) -> None:
        # The lock may have expired mid-fetch and belong to someone else now.
        with contextlib.suppress(LockError):
            await lock.release()

    async def _refresh(self, redis: Redis, url: str) -> list[T] | None:
        """Cache-miss path: fetch behind a single-flight lock. Returns None when
        the fetch fails or another instance holds the lock — callers fall back."""
        lock = self._lock(redis, blocking=False)
        if not await lock.acquire():
            return None
        try:
            items, etag = await self._fetch(url)
            await self._store(redis, items, etag)
            return items
        except Exception:  # noqa: BLE001 — any refresh failure falls back to a cached layer
            logger.warning(
                "%s refresh from %s failed; falling back",
                self.prefix,
                url,
                exc_info=True,
            )
            return None
        finally:
            await self._release(lock)

    async def get(self) -> list[T]:
        """The current catalog, through memo → Redis → CDN → last_good → bundled."""
        url = self.url
        if (
            self._memo is not None
            and self._memo[1] == url
            and monotonic() - self._memo[0] < self._memo_ttl_seconds
        ):
            return self._memo[2]

        items: list[T] | None = None
        if url:
            redis = get_redis()
            try:
                cached = await redis.get(self.cache_key)
                if cached:
                    items = self._loads(cached)
                else:
                    items = await self._refresh(redis, url)
                    if items is None:
                        last_good = await redis.get(self.last_good_key)
                        if last_good:
                            items = self._loads(last_good)
            except Exception:  # noqa: BLE001 — any Redis failure falls back to the bundled snapshot
                logger.warning(
                    "%s read from Redis failed; using bundled snapshot",
                    self.prefix,
                    exc_info=True,
                )

        # No URL configured means "bundled snapshot only" — never serve a
        # Redis entry left over from a previously configured URL.
        if items is None:
            items = self.bundled()
        self._memo = (monotonic(), url, items)
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

        # Same lock as the lazy refresh: block briefly rather than skip, so an
        # in-flight cache-miss fetch finishes (and can't clobber our result)
        # before the force-fetch stores the authoritative content.
        redis = get_redis()
        lock = self._lock(redis, blocking=True)
        if not await lock.acquire():
            raise ValueError("another catalog refresh is in progress; retry shortly")
        try:
            items, etag = await self._fetch(url)
            await self._store(redis, items, etag)
        finally:
            await self._release(lock)
        self.invalidate_memo()

        previous_keys = {self._key(item) for item in previous}
        current_keys = {self._key(item) for item in items}
        return SyncResult(
            added=sorted(current_keys - previous_keys),
            removed=sorted(previous_keys - current_keys),
            count=len(items),
            fetched_at=datetime.now(UTC),
        )
