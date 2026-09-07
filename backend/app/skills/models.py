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
    bundle: dict = Field(sa_column=json_column())


class AgentSkillDB(BaseDBModel, table=True):
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_id"),)
    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", index=True)
    skill_id: UUID = Field(foreign_key="skills.id", ondelete="CASCADE", index=True)
