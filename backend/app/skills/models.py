from uuid import UUID

from sqlalchemy import JSON, Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models import BaseDBModel, TimestampMixin
from app.skills.schemas import SkillBundle, SkillFile


class SkillDB(BaseDBModel, table=True):
    """One skill: its SKILL.md text and supporting files.

    `content` is the source of truth — the whole SKILL.md, frontmatter
    included. `name` and `description` are copied out of that frontmatter on
    every save so the library list and the graph-wide name check never read
    or parse the document. There are no versions: a save replaces the skill
    in place and every agent using it picks the new content up on its next
    run (a run in flight keeps the copy frozen on its thread).
    """

    __tablename__ = "skills"

    owner_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=64, index=True)
    description: str = Field(max_length=1024)
    content: str = Field(sa_column=Column(Text, nullable=False))
    # JSONB on Postgres; plain JSON elsewhere (the test suite runs on SQLite).
    files: list = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    # Optimistic-concurrency token: +1 per save, a stale one is refused.
    revision: int = Field(default=1, nullable=False)

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
