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
        otherwise unordered, which skips the sort for full scans."""
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
