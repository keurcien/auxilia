"""Postgres CRUD for the ``runs`` audit table.

Repository is intentionally narrow: it persists what the service hands it. It
does not own state transitions, validate input, or enforce ordering — those
live in ``service`` / ``worker``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select

from app.agents.runs.models import RunDB
from app.repository import BaseRepository


class RunRepository(BaseRepository[RunDB]):
    async def list_by_thread(self, thread_id: str, limit: int = 50) -> list[RunDB]:
        stmt = (
            select(RunDB)
            .where(RunDB.thread_id == thread_id)
            .order_by(desc(RunDB.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(self, run_id: UUID, user_id: UUID) -> RunDB | None:
        stmt = select(RunDB).where(RunDB.id == run_id, RunDB.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
