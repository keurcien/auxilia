"""One-shot import of usage that predates the ledger, read back from checkpoints.

Runs once per deployment history, on a dispatcher instance, behind an advisory
lock. Rows dedupe on (thread_id, message_id) against what the recorder wrote,
so an interrupted import simply starts over on the next boot. Prices are the
catalog's current ones, as for the per-conversation estimate. History only
covers what checkpoints retained: deleted threads, and tool-discovery router
calls (never checkpointed), are absent.
"""

import asyncio
import hashlib
import logging
from datetime import datetime

from langchain_core.messages import AIMessage
from sqlalchemy import text

from app.database import AsyncSessionLocal, engine
from app.runtime.api.costs import decode_message_write
from app.runtime.api.protocol_repository import CheckpointWriteRepository
from app.runtime.checkpoints import checkpoint_thread_id
from app.threads.models import ThreadDB
from app.usage.recorder import UsageAttribution, load_catalog, usage_row
from app.usage.repository import UsageLedgerStateRepository, UsageRepository


logger = logging.getLogger(__name__)

THREAD_BATCH = 200
INSERT_BATCH = 500
# Yield between threads so the import never starves live requests.
THREAD_PAUSE_SECONDS = 0.02
LOCK_SQL = "hashtext('auxilia.llm_usage_backfill')"


def _message_key(message: AIMessage) -> str:
    return message.id or (
        "sha256:" + hashlib.sha256(message.model_dump_json().encode()).hexdigest()
    )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class UsageBackfill:
    async def run(self) -> None:
        try:
            async with engine.connect() as lock:
                acquired = await lock.scalar(
                    text(f"SELECT pg_try_advisory_lock({LOCK_SQL})")
                )
                await lock.commit()
                if not acquired:
                    return
                try:
                    await self._run()
                finally:
                    await lock.execute(text(f"SELECT pg_advisory_unlock({LOCK_SQL})"))
                    await lock.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "LLM usage history import failed; it will retry on restart"
            )

    async def _run(self) -> None:
        async with AsyncSessionLocal() as db:
            state = await UsageLedgerStateRepository(db).get()
        if state is None or state.backfill_completed_at is not None:
            return
        logger.info("Importing LLM usage history from checkpoints")
        catalog = await load_catalog()
        cursor: tuple[datetime, str] | None = None
        imported = 0
        while True:
            async with AsyncSessionLocal() as db:
                threads = await UsageRepository(db).threads_created_before(
                    state.tracking_started_at, cursor, THREAD_BATCH
                )
            if not threads:
                break
            for thread in threads:
                try:
                    imported += await self._thread(thread, catalog)
                except Exception:  # noqa: BLE001 — one bad thread must not stop the import
                    logger.warning(
                        "Could not import usage history of thread %s",
                        thread.id,
                        exc_info=True,
                    )
                await asyncio.sleep(THREAD_PAUSE_SECONDS)
            last = threads[-1]
            cursor = (last.created_at, last.id)
        async with AsyncSessionLocal() as db:
            await UsageLedgerStateRepository(db).mark_backfill_completed()
            await db.commit()
        logger.info("LLM usage history imported: %d calls", imported)

    async def _thread(self, thread: ThreadDB, catalog) -> int:
        earliest: dict[str, tuple[datetime, AIMessage]] = {}
        async with AsyncSessionLocal() as db:
            attribution = await UsageAttribution.for_thread(db, thread)
            writes = CheckpointWriteRepository(db).iter_timed_message_writes(
                checkpoint_thread_id(thread.workspace_id, thread.id)
            )
            async for type_tag, blob, ts in writes:
                occurred_at = _parse_ts(ts) or thread.created_at
                for message in await asyncio.to_thread(
                    decode_message_write, type_tag, blob
                ):
                    # A message recurs in later writes (compaction rewrites
                    # the list): date it by its first write, and keep a copy
                    # that still carries usage.
                    key = _message_key(message)
                    seen = earliest.get(key)
                    if seen is None:
                        earliest[key] = (occurred_at, message)
                        continue
                    kept = (
                        message
                        if message.usage_metadata and not seen[1].usage_metadata
                        else seen[1]
                    )
                    earliest[key] = (min(seen[0], occurred_at), kept)
            rows = []
            for key, (occurred_at, message) in earliest.items():
                row = usage_row(message, attribution, catalog, occurred_at)
                if row is not None:
                    rows.append({**row, "message_id": key})
            repository = UsageRepository(db)
            for start in range(0, len(rows), INSERT_BATCH):
                await repository.insert_many(rows[start : start + INSERT_BATCH])
            await db.commit()
        return len(rows)
