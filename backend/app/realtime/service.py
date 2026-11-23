from collections.abc import AsyncGenerator
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.realtime.events import WorkspaceEventStream
from app.realtime.repository import WorkspaceEventOutboxRepository
from app.realtime.schemas import WorkspaceEventKind
from app.redis_client import get_redis


async def stage_workspace_event(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    kind: WorkspaceEventKind,
    target_user_id: UUID | None = None,
    thread_id: str | None = None,
) -> None:
    """Add an invalidation to the caller's transaction.

    The relay cannot observe this row until the transaction commits, so clients
    never receive an invalidation for data that later rolls back.
    """
    await WorkspaceEventOutboxRepository(db).enqueue(
        workspace_id=workspace_id,
        kind=kind.value,
        target_user_id=target_user_id,
        thread_id=thread_id,
    )


class WorkspaceRealtimeService:
    def __init__(self, redis: Redis | None = None):
        self.redis = redis or get_redis()

    async def stream(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        last_event_id: str | None,
    ) -> AsyncGenerator[str]:
        events = WorkspaceEventStream(workspace_id, self.redis)
        cursor = last_event_id or await events.latest_id()
        yield "retry: 3000\nevent: sync\ndata: {}\n\n"
        while True:
            batch = await events.read_batch(cursor)
            if batch is None:
                yield ": keep-alive\n\n"
                continue
            cursor, entries = batch
            for event in entries:
                if event.target_user_id is None or event.target_user_id == str(user_id):
                    yield event.sse()
