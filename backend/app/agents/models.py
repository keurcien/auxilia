from enum import Enum
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Boolean, Column, Field, SQLModel, String, Text

from app.models import BaseDBModel


ALLOWED_COLORS = {
    "#6C5CE7",
    "#00B894",
    "#E17055",
    "#0984E3",
    "#FDCB6E",
    "#E84393",
    "#9E9E9E",
}


class PermissionLevel(str, Enum):
    member = "member"
    editor = "editor"
    admin = "admin"


class ToolStatus(str, Enum):
    always_allow = "always_allow"
    needs_approval = "needs_approval"
    disabled = "disabled"


class AgentMCPServerBase(SQLModel):
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False)
    tools: dict[str, ToolStatus] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class AgentMCPServerDB(AgentMCPServerBase, BaseDBModel, table=True):
    __tablename__ = "agent_mcp_servers"


class AgentBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    instructions: str = Field(sa_column=Column(Text, nullable=False))
    owner_id: UUID = Field(foreign_key="users.id", nullable=False)
    emoji: str | None = Field(default=None, max_length=10, nullable=True)
    color: str | None = Field(default=None, max_length=7, nullable=True)
    description: str | None = Field(
        default=None, max_length=255, sa_column=Column(String(255), nullable=True)
    )


class AgentDB(AgentBase, BaseDBModel, table=True):
    __tablename__ = "agents"

    is_archived: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    has_code_interpreter: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    tag_id: UUID | None = Field(
        default=None,
        foreign_key="tags.id",
        ondelete="SET NULL",
        index=True,
        nullable=True,
    )


class AgentUserPermissionDB(BaseDBModel, table=True):
    __tablename__ = "agent_user_permissions"
    __table_args__ = (
        UniqueConstraint("agent_id", "user_id", name="uq_agent_user_permission"),
    )

    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    permission: PermissionLevel = Field(nullable=False)


class AgentTeamDB(BaseDBModel, table=True):
    __tablename__ = "agent_teams"
    __table_args__ = (UniqueConstraint("agent_id", "team_id", name="uq_agent_team"),)

    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", nullable=False)
    team_id: UUID = Field(
        foreign_key="teams.id", ondelete="CASCADE", index=True, nullable=False
    )


class AgentSubagentDB(BaseDBModel, table=True):
    __tablename__ = "agent_subagents"
    __table_args__ = (
        UniqueConstraint(
            "supervisor_id",
            "subagent_id",
            name="uq_agent_subagent",
        ),
    )

    supervisor_id: UUID = Field(foreign_key="agents.id", nullable=False)
    subagent_id: UUID = Field(foreign_key="agents.id", nullable=False)
