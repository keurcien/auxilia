from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Integer, delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlmodel import col, select

from app.agents.models import AgentDB
from app.repository import BaseRepository
from app.skills.models import AgentSkillDB, SkillDB, SkillSourceDB, SkillVersionDB
from app.skills.schemas import SCRIPTS_DIR


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


class json_script_count(FunctionElement):  # SQL function, named like one
    """How many of a skill's files sit under `scripts/` — the same rule as
    `schemas.is_script`, evaluated in SQL so the list never loads the files.
    A scalar subquery over the JSON array on both dialects."""

    type = Integer()
    inherit_cache = True


_SCRIPTS_PREFIX = f"{SCRIPTS_DIR}/"


@compiles(json_script_count)
def _json_script_count(element, compiler, **kw) -> str:
    files = compiler.process(element.clauses, **kw)
    return (
        f"(SELECT count(*) FROM json_each({files}) AS f "
        f"WHERE substr(json_extract(f.value, '$.path'), 1, {len(_SCRIPTS_PREFIX)}) "
        f"= '{_SCRIPTS_PREFIX}')"
    )


@compiles(json_script_count, "postgresql")
def _jsonb_script_count(element, compiler, **kw) -> str:
    files = compiler.process(element.clauses, **kw)
    return (
        f"(SELECT count(*) FROM jsonb_array_elements({files}) AS f "
        f"WHERE substr(f->>'path', 1, {len(_SCRIPTS_PREFIX)}) = '{_SCRIPTS_PREFIX}')"
    )


def _latest_version_digest():
    """Scalar subquery: the digest of the newest version a sync stored for the
    skill — an update is available when it differs from the skill's own."""
    return (
        select(SkillVersionDB.digest)
        .where(col(SkillVersionDB.skill_id) == col(SkillDB.id))
        .order_by(col(SkillVersionDB.created_at).desc(), col(SkillVersionDB.id))
        .limit(1)
        .correlate(SkillDB)
        .scalar_subquery()
    )


def _agent_count():
    """Scalar subquery: how many agents have the skill enabled."""
    return (
        select(func.count())
        .select_from(AgentSkillDB)
        .where(col(AgentSkillDB.skill_id) == col(SkillDB.id))
        .correlate(SkillDB)
        .scalar_subquery()
    )


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
            json_script_count(SkillDB.files).label("script_count"),
            _agent_count().label("agent_count"),
            SkillDB.source_id,
            SkillDB.source_path,
            SkillDB.source_revision,
            SkillDB.digest,
            SkillDB.missing_upstream,
            SkillSourceDB.name.label("source_name"),
            _latest_version_digest().label("latest_digest"),
        )
        stmt = stmt.select_from(SkillDB).outerjoin(
            SkillSourceDB, col(SkillSourceDB.id) == col(SkillDB.source_id)
        )
        stmt = stmt.order_by(col(SkillDB.updated_at).desc(), SkillDB.id)
        return (await self.db.execute(stmt)).all()

    # -- sourced skills and their versions ------------------------------------

    async def get_source(self, source_id: UUID) -> SkillSourceDB | None:
        return await self.db.get(SkillSourceDB, source_id)

    async def list_for_source(self, source_id: UUID) -> list[SkillDB]:
        stmt = (
            select(SkillDB)
            .where(SkillDB.source_id == source_id)
            .order_by(col(SkillDB.name))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def latest_version(self, skill_id: UUID) -> SkillVersionDB | None:
        stmt = (
            select(SkillVersionDB)
            .where(SkillVersionDB.skill_id == skill_id)
            .order_by(col(SkillVersionDB.created_at).desc(), col(SkillVersionDB.id))
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_version(self, skill_id: UUID, digest: str) -> SkillVersionDB | None:
        stmt = select(SkillVersionDB).where(
            SkillVersionDB.skill_id == skill_id, SkillVersionDB.digest == digest
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def record_version(
        self,
        skill_id: UUID,
        *,
        digest: str,
        revision: str,
        content: str,
        files: list[dict],
    ) -> SkillVersionDB:
        """The newest version seen upstream. A digest seen before is moved to
        the front (its `created_at` bumped) rather than duplicated, so an
        upstream revert reads as "this older version is now the latest"."""
        version = await self.get_version(skill_id, digest)
        if version is None:
            version = SkillVersionDB(
                skill_id=skill_id,
                digest=digest,
                revision=revision,
                content=content,
                files=files,
            )
        else:
            version.revision = revision
            version.created_at = datetime.now(UTC)
        self.db.add(version)
        await self.db.flush()
        return version

    async def detach_from_source(self, source_id: UUID) -> None:
        """Its skills become in-app skills (editable, no pin); their stored
        versions go with the source."""
        ids_stmt = select(SkillDB.id).where(SkillDB.source_id == source_id)
        skill_ids = list((await self.db.execute(ids_stmt)).scalars().all())
        if skill_ids:
            await self.db.execute(
                delete(SkillVersionDB).where(
                    col(SkillVersionDB.skill_id).in_(skill_ids)
                )
            )
        await self.db.execute(
            update(SkillDB)
            .where(col(SkillDB.source_id) == source_id)
            .values(
                source_id=None,
                source_path=None,
                source_revision=None,
                missing_upstream=False,
            )
        )

    async def list_agents_using(self, skill_id: UUID):
        """`(id, name, emoji, color)` of every agent the skill is enabled on,
        by name — the skill page's "used by" list and the delete guard."""
        stmt = (
            select(AgentDB.id, AgentDB.name, AgentDB.emoji, AgentDB.color)
            .join(AgentSkillDB, col(AgentSkillDB.agent_id) == col(AgentDB.id))
            .where(AgentSkillDB.skill_id == skill_id)
            .order_by(col(AgentDB.name), col(AgentDB.id))
        )
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
        """`(id, name, description, script_count)` of the agent's skills, by name."""
        stmt = (
            select(
                SkillDB.id,
                SkillDB.name,
                SkillDB.description,
                json_script_count(SkillDB.files).label("script_count"),
            )
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
