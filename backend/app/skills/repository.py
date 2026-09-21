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
    # The only interpolations are `_SCRIPTS_PREFIX` and its length, both module
    # constants; the JSON column itself is compiled by SQLAlchemy. Nothing here
    # is user input, so the f-string cannot carry one.
    files = compiler.process(element.clauses, **kw)
    return (
        f"(SELECT count(*) FROM json_each({files}) AS f "  # nosec B608
        f"WHERE substr(json_extract(f.value, '$.path'), 1, {len(_SCRIPTS_PREFIX)}) "
        f"= '{_SCRIPTS_PREFIX}')"
    )


@compiles(json_script_count, "postgresql")
def _jsonb_script_count(element, compiler, **kw) -> str:
    # Same as above: module constants only, never user input.
    files = compiler.process(element.clauses, **kw)
    return (
        f"(SELECT count(*) FROM jsonb_array_elements({files}) AS f "  # nosec B608
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
            SkillDB.source_url,
            SkillDB.source_path,
            SkillDB.source_revision,
            SkillDB.digest,
            SkillDB.missing_upstream,
            SkillSourceDB.name.label("source_name"),
            SkillSourceDB.kind.label("source_kind"),
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
        upstream revert reads as "this older version is now the latest".

        `created_at` is set here rather than left to the column default, on
        both paths. The default is `now()`, which is *transaction* time on
        Postgres and second-resolution on SQLite, so two versions recorded
        close together tied — and `latest_version` broke the tie on a random
        UUID, which is how `update_available` came to be a coin flip.
        """
        version = await self.get_version(skill_id, digest)
        if version is None:
            version = SkillVersionDB(
                skill_id=skill_id,
                digest=digest,
                revision=revision,
                content=content,
                files=files,
                created_at=datetime.now(UTC),
            )
        else:
            version.revision = revision
            version.created_at = datetime.now(UTC)
        self.db.add(version)
        await self.db.flush()
        return version

    async def detach_from_source(self, source_id: UUID) -> None:
        """Its skills stay, detached: everything the repository gave them —
        the document, the files, the `scripts/`, the commit they are pinned
        to — is already in the row, so they keep running exactly as they
        were. Only the link goes, which freezes the *content*: nothing here
        writes a skill whose files came from somewhere else, and there is
        nothing to adopt until the repository is connected again. Deleting
        one from the library stays allowed.

        `missing_upstream` is cleared with the link. It is the last sync's
        answer about a repository this skill no longer has, and a detached
        row saying "no longer in its repository" reads as a bug.

        `source_url` is *not* cleared: it is the provenance, not the link,
        and it is what makes reconnecting the same repository reclaim these
        rows rather than import a second copy of each.

        The stored versions go with the source: they are updates only an
        adopt against a connected repository can apply, and the next sync
        records whichever of them still exists.
        """
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
            .values(source_id=None, missing_upstream=False)
        )

    async def list_reclaimable(self, url: str) -> list[SkillDB]:
        """The skills *this* repository left behind when it was disconnected:
        the pin (`source_revision`, written only by a sync or an adopt), no
        live link, and the same origin. A sync claims the ones whose names it
        finds again, which is what makes reconnecting a repository re-pin its
        own rows instead of importing a second copy of each.

        Scoped to the URL, deliberately. Claiming on the name alone let *any*
        repository that happened to use a name take over another's row —
        content, id, and every agent binding pointing at it — and there is no
        undo for that. Another repository's leftovers are not this sync's to
        claim; they are simply a name already taken, reported as such.

        The pin is `source_revision` and not `digest` — every save computes a
        digest, so a skill written in the app would otherwise look detached.
        """
        stmt = (
            select(SkillDB)
            .where(
                col(SkillDB.source_id).is_(None),
                col(SkillDB.source_revision).is_not(None),
                SkillDB.source_url == url,
            )
            .order_by(col(SkillDB.name))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_all_names(self):
        """`(id, name)` for the whole library — the one namespace a sync and
        a save both have to fit into, read in a single query."""
        stmt = select(SkillDB.id, SkillDB.name)
        return (await self.db.execute(stmt)).all()

    async def get_by_name(self, name: str) -> SkillDB | None:
        stmt = select(SkillDB).where(SkillDB.name == name)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_agents_by_skill(self):
        """`(skill_id, id, name, emoji, color)` for every enabled skill, in one
        query — the library shows each row's agents as avatars, and a row per
        skill would be a query per row."""
        stmt = (
            select(
                AgentSkillDB.skill_id,
                AgentDB.id,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
            )
            .join(AgentSkillDB, col(AgentSkillDB.agent_id) == col(AgentDB.id))
            .order_by(col(AgentDB.name), col(AgentDB.id))
        )
        return (await self.db.execute(stmt)).all()

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
