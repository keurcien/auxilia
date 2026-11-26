from uuid import UUID

from sqlalchemy import case, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.artifacts.models import GALLERY_ORIGIN, ArtifactDB
from app.repository import BaseRepository


class ArtifactRepository(BaseRepository[ArtifactDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(ArtifactDB, db)
        self.workspace_id = workspace_id

    async def list_for_thread(
        self, thread_id: str, after: UUID | None = None
    ) -> list[ArtifactDB]:
        """A page of the thread's artifacts in (created_at, id) order.

        Keyset on the last row seen, so rows published between page fetches
        never shift a page boundary the way OFFSET would.
        """
        stmt = select(ArtifactDB).where(
            ArtifactDB.workspace_id == self.workspace_id,
            ArtifactDB.thread_id == thread_id,
            ArtifactDB.origin != GALLERY_ORIGIN,
        )
        if after is not None:
            cursor = (
                select(ArtifactDB.created_at, ArtifactDB.id)
                .where(
                    ArtifactDB.workspace_id == self.workspace_id,
                    ArtifactDB.thread_id == thread_id,
                    ArtifactDB.id == after,
                )
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
            .where(
                ArtifactDB.workspace_id == self.workspace_id,
                ArtifactDB.thread_id == thread_id,
                ArtifactDB.source_path == path,
                ArtifactDB.origin == "artifact",
            )
            .order_by(col(ArtifactDB.created_at).desc(), col(ArtifactDB.id).desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def paths_in_thread(self, thread_id: str) -> set[str]:
        stmt = select(ArtifactDB.source_path).where(
            ArtifactDB.workspace_id == self.workspace_id,
            ArtifactDB.thread_id == thread_id,
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def list_stored_in(
        self,
        thread_id: str,
        kind: str,
        bucket: str | None,
        endpoint: str | None,
    ) -> list[ArtifactDB]:
        """Latest stored thread file for every sandbox path."""
        stmt = (
            select(ArtifactDB)
            .where(
                ArtifactDB.workspace_id == self.workspace_id,
                ArtifactDB.thread_id == thread_id,
                ArtifactDB.origin != GALLERY_ORIGIN,
                ArtifactDB.storage_kind == kind,
                col(ArtifactDB.storage_bucket).is_not_distinct_from(bucket),
                col(ArtifactDB.storage_endpoint).is_not_distinct_from(endpoint),
            )
            .order_by(
                col(ArtifactDB.source_path),
                col(ArtifactDB.created_at).desc(),
                # Rows written in one transaction share `created_at`; a presented
                # artifact still follows and must win over the original attachment.
                case((col(ArtifactDB.origin) == "artifact", 1), else_=0).desc(),
                col(ArtifactDB.id).desc(),
            )
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        latest: dict[str, ArtifactDB] = {}
        for row in rows:
            latest.setdefault(row.source_path, row)
        return list(latest.values())

    async def in_thread(
        self, thread_id: str, artifact_id: UUID, *, for_update: bool = False
    ) -> ArtifactDB | None:
        stmt = select(ArtifactDB).where(
            ArtifactDB.workspace_id == self.workspace_id,
            ArtifactDB.thread_id == thread_id,
            ArtifactDB.id == artifact_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def attachments_by_ids(
        self, thread_id: str, attachment_ids: list[UUID]
    ) -> list[ArtifactDB]:
        if not attachment_ids:
            return []
        stmt = select(ArtifactDB).where(
            ArtifactDB.workspace_id == self.workspace_id,
            ArtifactDB.thread_id == thread_id,
            ArtifactDB.origin == "attachment",
            col(ArtifactDB.id).in_(attachment_ids),
        )
        result = await self.db.execute(stmt)
        rows = {row.id: row for row in result.scalars().all()}
        return [rows[item_id] for item_id in attachment_ids if item_id in rows]

    async def by_ids(
        self, thread_id: str, artifact_ids: list[UUID]
    ) -> list[ArtifactDB]:
        if not artifact_ids:
            return []
        stmt = select(ArtifactDB).where(
            ArtifactDB.workspace_id == self.workspace_id,
            ArtifactDB.thread_id == thread_id,
            col(ArtifactDB.id).in_(artifact_ids),
        )
        result = await self.db.execute(stmt)
        rows = {row.id: row for row in result.scalars().all()}
        return [rows[item_id] for item_id in artifact_ids if item_id in rows]

    async def save(self, row: ArtifactDB) -> ArtifactDB:
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row
