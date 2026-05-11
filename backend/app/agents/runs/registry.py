"""Redis-backed live state for runs.

The registry is a thin, typed wrapper over a Redis hash plus one helper key per
thread. It does **only** I/O and serialisation — no state-machine logic, no
event dispatch, no business decisions.

Keys:
- ``run:{run_id}``           — hash holding a serialised ``RunRecord``.
- ``thread:{tid}:active_run`` — string holding the active ``run_id`` for the
  thread; used as the single-active-run mutex via ``SET NX EX``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunRecord,
    RunState,
    is_active,
    utcnow,
)


# --- key helpers -------------------------------------------------------------


def _run_key(run_id: UUID) -> str:
    return f"run:{run_id}"


def _active_run_key(thread_id: str) -> str:
    return f"thread:{thread_id}:active_run"


# --- (de)serialisation -------------------------------------------------------

# Redis hash values are strings. We render datetimes as ISO8601, UUIDs as str,
# enums by .value, and dict fields as JSON. Everything round-trips through
# ``RunRecord`` so the rest of the codebase stays in pure Python.

_DICT_FIELDS = frozenset({"interrupt", "error", "input_summary"})
_DATETIME_FIELDS = frozenset(
    {"created_at", "updated_at", "started_at", "completed_at", "heartbeat_at"}
)
_UUID_FIELDS = frozenset({"id", "user_id", "agent_id"})


def _encode(record: RunRecord) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in asdict(record).items():
        if value is None:
            continue
        if key in _DATETIME_FIELDS:
            out[key] = value.isoformat() if isinstance(value, datetime) else str(value)
        elif key in _UUID_FIELDS:
            out[key] = str(value)
        elif key == "status":
            out[key] = RunState(value).value
        elif key == "multitask_strategy":
            out[key] = MultitaskStrategy(value).value
        elif key == "cancellation_reason":
            out[key] = CancellationReason(value).value
        elif key in _DICT_FIELDS:
            out[key] = json.dumps(value)
        else:
            out[key] = str(value)
    return out


def _decode(raw: dict[str, str]) -> RunRecord:
    if not raw:
        raise KeyError("empty hash")
    kwargs: dict[str, Any] = {}
    record_fields = {f.name for f in fields(RunRecord)}
    for key, value in raw.items():
        if key not in record_fields:
            continue  # forward-compat: ignore unknown keys
        if key in _DATETIME_FIELDS:
            kwargs[key] = datetime.fromisoformat(value)
        elif key in _UUID_FIELDS:
            kwargs[key] = UUID(value)
        elif key == "status":
            kwargs[key] = RunState(value)
        elif key == "multitask_strategy":
            kwargs[key] = MultitaskStrategy(value)
        elif key == "cancellation_reason":
            kwargs[key] = CancellationReason(value)
        elif key in _DICT_FIELDS:
            kwargs[key] = json.loads(value)
        else:
            kwargs[key] = value
    return RunRecord(**kwargs)


# --- registry ---------------------------------------------------------------


# Atomic compare-and-delete: only DEL the active_run pointer if it still
# matches the run that's clearing it. Prevents a finishing run from clobbering
# the pointer set by a follow-up.
_CLEAR_ACTIVE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class RunRegistry:
    """Live state of every run, mirrored from Redis."""

    DEFAULT_RUN_TTL_SECONDS: int = 24 * 60 * 60  # 24h after terminal state.
    DEFAULT_ACTIVE_TTL_SECONDS: int = 30 * 60     # max active run duration.

    def __init__(self, redis: Redis):
        self.redis = redis

    # ---- run hash ----

    async def create(
        self,
        record: RunRecord,
        ttl_seconds: int = DEFAULT_RUN_TTL_SECONDS,
    ) -> None:
        key = _run_key(record.id)
        await self.redis.hset(key, mapping=_encode(record))
        await self.redis.expire(key, ttl_seconds)

    async def get(self, run_id: UUID) -> RunRecord | None:
        raw = await self.redis.hgetall(_run_key(run_id))
        if not raw:
            return None
        return _decode(raw)

    async def update(self, run_id: UUID, **changes: Any) -> RunRecord:
        """Partial update. Always bumps ``updated_at``.

        Caller is responsible for valid state transitions (use ``state.transition``).
        Pass ``None`` to clear an optional field.
        """
        current = await self.get(run_id)
        if current is None:
            raise KeyError(run_id)
        updated = replace(current, updated_at=utcnow(), **changes)
        # Re-encode the full record. HSET is idempotent and partial keys would
        # leave stale values from a prior status if we didn't.
        await self.redis.delete(_run_key(run_id))
        await self.redis.hset(_run_key(run_id), mapping=_encode(updated))
        await self.redis.expire(_run_key(run_id), self.DEFAULT_RUN_TTL_SECONDS)
        return updated

    async def heartbeat(self, run_id: UUID) -> None:
        """Cheap, no-allocation heartbeat. Bypasses ``update`` to skip a roundtrip."""
        now = utcnow().isoformat()
        await self.redis.hset(
            _run_key(run_id), mapping={"heartbeat_at": now, "updated_at": now}
        )

    # ---- active run mutex ----

    async def try_set_active(
        self,
        thread_id: str,
        run_id: UUID,
        ttl_seconds: int = DEFAULT_ACTIVE_TTL_SECONDS,
    ) -> bool:
        """``SET NX EX``. Returns ``True`` if this run is now the active run."""
        return bool(
            await self.redis.set(
                _active_run_key(thread_id), str(run_id), nx=True, ex=ttl_seconds
            )
        )

    async def get_active(self, thread_id: str) -> UUID | None:
        raw = await self.redis.get(_active_run_key(thread_id))
        return UUID(raw) if raw else None

    async def clear_active_if_match(self, thread_id: str, run_id: UUID) -> bool:
        """Compare-and-delete: only release the mutex if we still own it."""
        result = await self.redis.eval(
            _CLEAR_ACTIVE_LUA, 1, _active_run_key(thread_id), str(run_id)
        )
        return bool(result)

    # ---- reaper support ----

    async def _scan_all(self) -> list[RunRecord]:
        """Yield every ``RunRecord`` currently stored in Redis (TTL: 24h).

        Note: ``run:*`` also matches sub-keys (``run:{id}:events`` Stream,
        ``run:{id}:control`` List, ``run:{id}:input`` String). The run hash is
        exactly ``run:{uuid}`` with one colon; we filter by colon count so
        ``HGETALL`` never gets handed a non-hash key (which would WRONGTYPE).
        """
        results: list[RunRecord] = []
        async for key in self.redis.scan_iter(match="run:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            if key_str.count(":") != 1:
                continue
            raw = await self.redis.hgetall(key)
            if not raw:
                continue
            try:
                results.append(_decode(raw))
            except (ValueError, KeyError):
                continue  # forward-compat: skip malformed
        return results

    async def scan_active(self) -> list[RunRecord]:
        """Active runs only. Used by the reaper to find orphans."""
        return [r for r in await self._scan_all() if is_active(r.status)]

    async def list_by_thread(
        self, thread_id: str, *, limit: int = 50
    ) -> list[RunRecord]:
        """All runs (active or terminal) for a thread, newest first.

        Bounded by Redis key TTL (24h) — older runs are gone, which is the
        intended retention. ``SCAN`` is non-blocking; for higher cardinality,
        switch to a per-thread sorted set index — out of scope for V1.
        """
        matches = [r for r in await self._scan_all() if r.thread_id == thread_id]
        matches.sort(key=lambda r: r.created_at, reverse=True)
        return matches[:limit]
