"""SQL over the LangGraph checkpoint tables the protocol facade reads directly.

langgraph's Postgres saver keeps, next to every checkpoint, the writes each
task produced (`checkpoint_writes`): one row per task per channel, holding
just that task's output — one tool result, one model turn. A checkpoint's
channel value, by contrast, is the whole conversation. So a single message is
cheapest to recover from the writes: scan the `messages`-channel rows and stop
at the first that carries the id, never materialising the thread.
"""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CheckpointWriteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def iter_message_writes(
        self, thread_id: str
    ) -> AsyncIterator[tuple[str, bytes]]:
        """`(type, blob)` of every `messages`-channel write of the thread, in
        every namespace, newest checkpoint first — streamed, so a caller that
        stops early never holds more than one write."""
        stmt = text(
            "SELECT type, blob FROM checkpoint_writes "
            "WHERE thread_id = :thread_id AND channel = 'messages' "
            "ORDER BY checkpoint_id DESC, idx ASC"
        )
        result = await self.db.stream(stmt, {"thread_id": thread_id})
        async for row in result:
            yield row.type, bytes(row.blob)
