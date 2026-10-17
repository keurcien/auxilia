from uuid import UUID

from sqlalchemy import tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.artifacts.models import ArtifactDB
from app.repository import BaseRepository


class ArtifactRepository(BaseRepository[ArtifactDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(ArtifactDB, db)

    async def list_for_thread(
        self, thread_id: str, after: UUID | None = None
    ) -> list[ArtifactDB]:
        """A page of the thread's artifacts in (created_at, id) order.

        Keyset on the last row seen, so rows published between page fetches
        never shift a page boundary the way OFFSET would.
        """
        stmt = select(ArtifactDB).where(ArtifactDB.thread_id == thread_id)
        if after is not None:
            cursor = (
                select(ArtifactDB.created_at, ArtifactDB.id)
                .where(ArtifactDB.thread_id == thread_id, ArtifactDB.id == after)
                .subquery()
            )
            stmt = stmt.where(
                tuple_(col(ArtifactDB.created_at), col(ArtifactDB.id))
                > tuple_(cursor.c.created_at, cursor.c.id)
            )
        stmt = stmt.order_by(col(ArtifactDB.created_at), col(ArtifactDB.id)).limit(100)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def at_path(self, thread_id: str, path: str) -> ArtifactDB | None:
        """The thread's artifact for a sandbox path. Threads from before in-place
        updates can hold several rows per path; the newest one is updated."""
        stmt = (
            select(ArtifactDB)
            .where(ArtifactDB.thread_id == thread_id, ArtifactDB.source_path == path)
            .order_by(col(ArtifactDB.created_at).desc(), col(ArtifactDB.id).desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def in_thread(
        self, thread_id: str, artifact_id: UUID, *, for_update: bool = False
    ) -> ArtifactDB | None:
        stmt = select(ArtifactDB).where(
            ArtifactDB.thread_id == thread_id, ArtifactDB.id == artifact_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, row: ArtifactDB) -> ArtifactDB:
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row
