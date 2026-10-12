from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.artifacts.models import ArtifactDB
from app.repository import BaseRepository


class ArtifactRepository(BaseRepository[ArtifactDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(ArtifactDB, db)

    async def list_for_thread(
        self, thread_id: str, offset: int = 0
    ) -> list[ArtifactDB]:
        stmt = (
            select(ArtifactDB)
            .where(ArtifactDB.thread_id == thread_id)
            .order_by(col(ArtifactDB.created_at), col(ArtifactDB.id))
            .offset(offset)
            .limit(100)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def published(
        self, thread_id: str, tool_call_id: str, path: str
    ) -> ArtifactDB | None:
        stmt = select(ArtifactDB).where(
            ArtifactDB.thread_id == thread_id,
            ArtifactDB.tool_call_id == tool_call_id,
            ArtifactDB.source_path == path,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def in_thread(self, thread_id: str, artifact_id: UUID) -> ArtifactDB | None:
        stmt = select(ArtifactDB).where(
            ArtifactDB.thread_id == thread_id, ArtifactDB.id == artifact_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def insert(self, row: ArtifactDB) -> ArtifactDB:
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row
