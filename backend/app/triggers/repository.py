from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.triggers.models import TriggerDB, TriggerType


class TriggerRepository(BaseRepository[TriggerDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(TriggerDB, db)
        self.workspace_id = workspace_id

    def _scope(self, stmt):
        if self.workspace_id is not None:
            stmt = stmt.where(TriggerDB.workspace_id == self.workspace_id)
        return stmt

    async def get(self, trigger_id: UUID) -> TriggerDB | None:
        stmt = self._scope(select(TriggerDB).where(TriggerDB.id == trigger_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[TriggerDB]:
        stmt = self._scope(select(TriggerDB)).order_by(TriggerDB.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_owner(self, owner_id: UUID) -> list[TriggerDB]:
        stmt = (
            select(TriggerDB)
            .where(TriggerDB.owner_id == owner_id)
            .order_by(TriggerDB.created_at.desc())
        )
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_webhook_id(self, webhook_id: UUID) -> TriggerDB | None:
        stmt = select(TriggerDB).where(
            TriggerDB.webhook_id == webhook_id,
            TriggerDB.trigger_type == TriggerType.webhook,
        )
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def claim_due(self, now: datetime, limit: int) -> list[TriggerDB]:
        """Lock and return active triggers whose next occurrence has passed.

        ``FOR UPDATE SKIP LOCKED`` makes concurrent scanner ticks (multiple
        instances) partition the due set instead of double-claiming: a row
        locked by one tick is invisible to the others. The claim completes when
        the caller advances ``next_run_at`` and commits.
        """
        stmt = (
            select(TriggerDB)
            .where(
                TriggerDB.is_active,
                TriggerDB.trigger_type == TriggerType.schedule,
                TriggerDB.next_run_at.is_not(None),  # type: ignore[union-attr]
                TriggerDB.next_run_at <= now,
            )
            .order_by(TriggerDB.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
