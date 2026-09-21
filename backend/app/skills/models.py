from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum as SAEnum,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models import BaseDBModel, TimestampMixin
from app.skills.schemas import SkillBundle, SkillFile, SkillSourceKind


def _json():
    return Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)


class SkillSourceDB(BaseDBModel, table=True):
    """A repository the workspace syncs skills from (GitHub or GitLab, any
    instance). Sync reads the repository at `ref`, resolved to a commit,
    and makes each skill *available*; it never changes what an agent runs.
    The token is encrypted at rest and only ever decrypted to resolve.

    `last_*` describe the last sync: `last_status` is one of ``ok``, ``auth``,
    ``not_found``, ``empty``, ``unavailable``, ``invalid`` — "not configured"
    / "permanently broken" / "nothing there yet" / "temporarily unavailable",
    told apart by type, not by message.
    """

    __tablename__ = "skill_sources"
    # A source *is* its (url, ref, subpath). The application check cannot stop
    # two admins connecting the same repository at once, and an expression
    # index is needed because a plain unique constraint lets NULL subpaths
    # collide freely.
    __table_args__ = (
        Index(
            "uq_skill_sources_identity",
            "url",
            "ref",
            text("coalesce(subpath, '')"),
            unique=True,
        ),
    )

    owner_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=120)
    kind: SkillSourceKind = Field(
        sa_column=Column(SAEnum(SkillSourceKind), nullable=False)
    )
    url: str = Field(max_length=500)
    ref: str = Field(default="main", max_length=200)
    subpath: str | None = Field(default=None, max_length=240)
    encrypted_token: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    last_revision: str | None = Field(default=None, max_length=80)
    last_synced_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_status: str | None = Field(default=None, max_length=20)
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    last_report: list = Field(default_factory=list, sa_column=_json())
    skill_count: int = Field(default=0, nullable=False)


class SkillVersionDB(BaseDBModel, table=True):
    """A version of a sourced skill as its repository held it at some sync:
    the frozen content and files, keyed by content digest. The newest row
    that differs from the skill's own `digest` is the update waiting to be
    adopted."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "digest", name="uq_skill_versions_digest"),
    )

    skill_id: UUID = Field(foreign_key="skills.id", ondelete="CASCADE", index=True)
    digest: str = Field(max_length=80, index=True)
    revision: str = Field(max_length=80)
    content: str = Field(sa_column=Column(Text, nullable=False))
    files: list = Field(default_factory=list, sa_column=_json())


class SkillDB(BaseDBModel, table=True):
    """One skill: its SKILL.md text and supporting files.

    `content` is the source of truth — the whole SKILL.md, frontmatter
    included. `name` and `description` are copied out of that frontmatter on
    every save so the library list and the graph-wide name check never read
    or parse the document. There are no versions: a save replaces the skill
    in place and every agent using it picks the new content up on its next
    run (a run in flight keeps the copy frozen on its thread).

    The library is **one namespace**: `name` is unique across the workspace.
    An agent addresses a skill by that name and reads its files under
    ``<root>/<name>/``, so two skills of one name can never be enabled
    together — and a library that allows the duplicate only moves the
    collision to the agent's config save, where the remedy ("rename one") is
    not always available. Refusing at the door is the same rule said once,
    early, where the caller can still act on it.
    """

    __tablename__ = "skills"

    owner_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=64, index=True, unique=True)
    description: str = Field(max_length=1024)
    content: str = Field(sa_column=Column(Text, nullable=False))
    # JSONB on Postgres; plain JSON elsewhere (the test suite runs on SQLite).
    files: list = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    # Optimistic-concurrency token: +1 per save, a stale one is refused.
    revision: int = Field(default=1, nullable=False)
    # Provenance, as two existing columns and no third state column.
    # `source_revision` is the pin — the commit the content was read at, and
    # only a sync or an adopt ever writes it — and `source_id` says whether
    # that repository is still connected:
    #
    #   source_revision None             → written in the app; editable here.
    #   source_revision + source_id      → pinned to `source_path` at that
    #                               commit; edited in the repository, a newer
    #                               `SkillVersionDB` adopted explicitly.
    #   source_revision, source_id None  → detached: the repository was
    #                               disconnected. The document, the files and
    #                               the `scripts/` are all in this row, so the
    #                               skill keeps running exactly as it was.
    #                               Its content is frozen — nothing here
    #                               edits files it cannot write — until the
    #                               repository is connected again, which
    #                               re-pins this row rather than importing a
    #                               second copy of it. Deleting the row is
    #                               still allowed.
    #
    # Not `digest`: every save computes one, in-app skills included. A skill
    # the last sync no longer found upstream keeps working and is flagged;
    # `ON DELETE SET NULL` is what makes a disconnect detach.
    source_id: UUID | None = Field(
        default=None, foreign_key="skill_sources.id", ondelete="SET NULL", index=True
    )
    # Which repository the content came from, as a URL rather than a foreign
    # key: the key is nulled when the source row goes, and this has to outlive
    # it. It is what a *reconnect* matches on, so only the repository that
    # left a skill behind can claim it back — matching on the name alone let
    # any repository that happened to use the name adopt another's row, under
    # the id agents are already bound to. It is also the only thing left that
    # can tell a reader where a detached skill came from.
    source_url: str | None = Field(default=None, max_length=500, index=True)
    # Where the skill sits in the repository, relative to its *root* and not
    # to the source's `subpath` (`sources.service._full_path`). Together with
    # `source_url` it identifies the skill, which is what a reclaim matches
    # on: two sources can share a URL with different subpaths and see the
    # same names, so the name alone would let one claim the other's rows.
    # Text, not a bounded varchar: a repository decides how deeply it nests a
    # skill, and a path longer than the bound raises a `DataError` — which is
    # not an `IntegrityError`, so the sync's savepoint would not catch it and
    # one pathological folder would abort the whole run mid-apply.
    source_path: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    source_revision: str | None = Field(default=None, max_length=80)
    digest: str | None = Field(default=None, max_length=80)
    missing_upstream: bool = Field(default=False, nullable=False)

    def to_bundle(self) -> SkillBundle:
        return SkillBundle(
            name=self.name,
            description=self.description,
            content=self.content,
            files=[SkillFile.model_validate(file) for file in self.files],
        )


class AgentSkillDB(TimestampMixin, SQLModel, table=True):
    """A skill enabled on an agent. Cascades with either side: an agent's
    deletion drops its bindings, and a user's deletion drops their skills'
    bindings on every agent. Deleting a skill *through the API* is refused
    while any binding exists."""

    __tablename__ = "agent_skills"

    agent_id: UUID = Field(
        foreign_key="agents.id", ondelete="CASCADE", primary_key=True
    )
    skill_id: UUID = Field(
        foreign_key="skills.id", ondelete="CASCADE", primary_key=True, index=True
    )
