from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Integer, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlmodel import col, select

from app.repository import BaseRepository
from app.skills.models import AgentSkillDB, SkillDB


class json_array_length(FunctionElement):  # SQL function, named like one
    """`jsonb_array_length` on Postgres, `json_array_length` on SQLite (the
    test suite), so the library list can count files without loading them."""

    type = Integer()
    inherit_cache = True


@compiles(json_array_length)
def _json_array_length(element, compiler, **kw) -> str:
    return f"json_array_length({compiler.process(element.clauses, **kw)})"


@compiles(json_array_length, "postgresql")
def _jsonb_array_length(element, compiler, **kw) -> str:
    return f"jsonb_array_length({compiler.process(element.clauses, **kw)})"


class SkillRepository(BaseRepository[SkillDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillDB, db)

    async def list_summaries(self):
        """Every skill's row minus the document and files, plus a file count —
        the library never loads a bundle it is not opening."""
        stmt = select(
            SkillDB.id,
            SkillDB.owner_id,
            SkillDB.name,
            SkillDB.description,
            SkillDB.revision,
            SkillDB.updated_at,
            json_array_length(SkillDB.files).label("file_count"),
        ).order_by(col(SkillDB.updated_at).desc(), SkillDB.id)
        return (await self.db.execute(stmt)).all()

    async def get_for_update(self, skill_id: UUID) -> SkillDB | None:
        """The row, locked for the rest of the transaction (save/delete)."""
        stmt = select(SkillDB).where(SkillDB.id == skill_id).with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_existing_ids(self, skill_ids: Iterable[UUID]) -> set[UUID]:
        ids = list(skill_ids)
        if not ids:
            return set()
        stmt = select(SkillDB.id).where(col(SkillDB.id).in_(ids))
        return set((await self.db.execute(stmt)).scalars().all())

    async def list_for_agents(self, agent_ids: Iterable[UUID]) -> list[SkillDB]:
        """The distinct skills enabled on any of the agents, by name — a
        supervisor and its subagents share one set at run time."""
        ids = list(agent_ids)
        if not ids:
            return []
        stmt = (
            select(SkillDB)
            .join(AgentSkillDB, col(AgentSkillDB.skill_id) == col(SkillDB.id))
            .where(col(AgentSkillDB.agent_id).in_(ids))
            .distinct()
            .order_by(col(SkillDB.name), col(SkillDB.id))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_names_for_agents(self, agent_ids: Iterable[UUID]):
        """`(skill_id, name)` for every skill enabled on any of the agents —
        what the graph-wide name check needs, and nothing heavier."""
        ids = list(agent_ids)
        if not ids:
            return []
        stmt = (
            select(SkillDB.id, SkillDB.name)
            .join(AgentSkillDB, col(AgentSkillDB.skill_id) == col(SkillDB.id))
            .where(col(AgentSkillDB.agent_id).in_(ids))
            .distinct()
        )
        return (await self.db.execute(stmt)).all()

    async def list_names(self, skill_ids: Iterable[UUID]):
        """`(skill_id, name)` for the given skills."""
        ids = list(skill_ids)
        if not ids:
            return []
        stmt = select(SkillDB.id, SkillDB.name).where(col(SkillDB.id).in_(ids))
        return (await self.db.execute(stmt)).all()

    async def list_attached(self, agent_id: UUID):
        """`(id, name, description)` of the agent's skills, by name."""
        stmt = (
            select(SkillDB.id, SkillDB.name, SkillDB.description)
            .join(AgentSkillDB, col(AgentSkillDB.skill_id) == col(SkillDB.id))
            .where(AgentSkillDB.agent_id == agent_id)
            .order_by(col(SkillDB.name))
        )
        return (await self.db.execute(stmt)).all()

    async def list_attached_ids(self, agent_id: UUID) -> set[UUID]:
        stmt = select(AgentSkillDB.skill_id).where(AgentSkillDB.agent_id == agent_id)
        return set((await self.db.execute(stmt)).scalars().all())

    async def is_attached(self, skill_id: UUID) -> bool:
        stmt = (
            select(AgentSkillDB.agent_id)
            .where(AgentSkillDB.skill_id == skill_id)
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none() is not None

    async def add_links(self, agent_id: UUID, skill_ids: Iterable[UUID]) -> None:
        for skill_id in skill_ids:
            self.db.add(AgentSkillDB(agent_id=agent_id, skill_id=skill_id))
        await self.db.flush()

    async def delete_links(self, agent_id: UUID, skill_ids: Iterable[UUID]) -> None:
        ids = list(skill_ids)
        if not ids:
            return
        stmt = delete(AgentSkillDB).where(
            col(AgentSkillDB.agent_id) == agent_id,
            col(AgentSkillDB.skill_id).in_(ids),
        )
        await self.db.execute(stmt)
