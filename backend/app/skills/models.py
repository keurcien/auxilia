from uuid import UUID

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models import BaseDBModel


def json_column():
    return Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)


class SkillDB(BaseDBModel, table=True):
    __tablename__ = "skills"
    owner_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    visibility: str = "private"
    revision: int = 1
    draft: dict = Field(sa_column=json_column())


class SkillVersionDB(BaseDBModel, table=True):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "number"),)
    skill_id: UUID = Field(foreign_key="skills.id", ondelete="CASCADE", index=True)
    number: int
    bundle: dict = Field(sa_column=json_column())


class AgentSkillDB(BaseDBModel, table=True):
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_id"),)
    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", index=True)
    skill_id: UUID = Field(foreign_key="skills.id", ondelete="CASCADE", index=True)
    version_id: UUID = Field(foreign_key="skill_versions.id", ondelete="RESTRICT")


class SkillTestDB(BaseDBModel, table=True):
    __tablename__ = "skill_tests"
    skill_id: UUID = Field(foreign_key="skills.id", ondelete="CASCADE", index=True)
    thread_id: str = Field(foreign_key="threads.id", ondelete="CASCADE", unique=True)
    bundle: dict = Field(sa_column=json_column())
    result: str | None = None
    notes: str = ""
