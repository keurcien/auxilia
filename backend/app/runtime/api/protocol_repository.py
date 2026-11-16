"""SQL over the LangGraph checkpoint tables the protocol facade reads directly.

langgraph's Postgres saver keeps, next to every checkpoint, the writes each
task produced (`checkpoint_writes`): one row per task per channel, holding
just that task's output — one tool result, one model turn. A checkpoint's
channel value, by contrast, is the whole conversation. So a single message is
cheapest to recover from the writes: scan the `messages`-channel rows and stop
at the first that carries the id, never materialising the thread.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CheckpointWriteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def iter_message_writes(
        self, thread_id: str, *, newest_first: bool = True
    ) -> AsyncGenerator[tuple[str, bytes], None]:
        """`(type, blob)` of every `messages`-channel write of the thread, in
        every namespace — streamed, so a caller that stops early never holds
        more than one write. Newest checkpoint first when `newest_first`;
        otherwise unordered, which avoids a sort for full scans."""
        query = (
            "SELECT type, blob FROM checkpoint_writes "
            "WHERE thread_id = :thread_id AND channel = 'messages' "
        )
        if newest_first:
            query += "ORDER BY checkpoint_id DESC, idx ASC"
        stmt = text(query)
        result = await self.db.stream(
            stmt.execution_options(yield_per=1), {"thread_id": thread_id}
        )
        try:
            async for row in result:
                yield row.type, bytes(row.blob)
        finally:
            await result.close()

    async def iter_timed_message_writes(
        self, thread_id: str
    ) -> AsyncGenerator[tuple[str, bytes, str | None], None]:
        """`(type, blob, ts)` of every `messages`-channel write, unordered;
        `ts` is the ISO timestamp of the checkpoint the write belongs to."""
        stmt = text(
            "SELECT w.type, w.blob, c.checkpoint->>'ts' AS ts "
            "FROM checkpoint_writes w "
            "LEFT JOIN checkpoints c ON c.thread_id = w.thread_id "
            "AND c.checkpoint_ns = w.checkpoint_ns "
            "AND c.checkpoint_id = w.checkpoint_id "
            "WHERE w.thread_id = :thread_id AND w.channel = 'messages'"
        )
        result = await self.db.stream(
            stmt.execution_options(yield_per=1), {"thread_id": thread_id}
        )
        try:
            async for row in result:
                yield row.type, bytes(row.blob), row.ts
        finally:
            await result.close()

    async def iter_namespace_message_writes(
        self, thread_id: str, checkpoint_ns: str
    ) -> AsyncGenerator[tuple[str, str, bytes], None]:
        """`(task_id, type, blob)` of the `messages`-channel writes of one
        namespace, newest checkpoint first, streamed like `iter_message_writes`."""
        stmt = text(
            "SELECT task_id, type, blob FROM checkpoint_writes "
            "WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns "
            "AND channel = 'messages' "
            "ORDER BY checkpoint_id DESC, idx ASC"
        )
        result = await self.db.stream(
            stmt.execution_options(yield_per=1),
            {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns},
        )
        try:
            async for row in result:
                yield row.task_id, row.type, bytes(row.blob)
        finally:
            await result.close()

    async def list_subgraph_namespaces(self, thread_id: str) -> list[str]:
        """The thread's non-root checkpoint namespaces, most recently written first."""
        stmt = text(
            "SELECT checkpoint_ns FROM checkpoints "
            "WHERE thread_id = :thread_id AND checkpoint_ns <> '' "
            "GROUP BY checkpoint_ns ORDER BY max(checkpoint_id) DESC"
        )
        result = await self.db.execute(stmt, {"thread_id": thread_id})
        return list(result.scalars())
