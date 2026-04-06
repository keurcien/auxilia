from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlmodel import Boolean, Column, DateTime, Field, SQLModel, String, Text


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
    user = "user"
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


class AgentMCPServerDB(AgentMCPServerBase, table=True):
    __tablename__ = "agent_mcp_servers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class AgentMCPServerCreate(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerUpdate(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerRead(AgentMCPServerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


# Agent Models (Database)
class AgentBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    instructions: str = Field(sa_column=Column(Text, nullable=False))
    owner_id: UUID = Field(foreign_key="users.id", nullable=False)
    emoji: str | None = Field(default=None, max_length=10, nullable=True)
    color: str | None = Field(default=None, max_length=7, nullable=True)
    description: str | None = Field(
        default=None, max_length=255, sa_column=Column(String(255), nullable=True)
    )


class AgentDB(AgentBase, table=True):
    __tablename__ = "agents"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    is_archived: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    sandbox: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class AgentCreate(SQLModel):
    name: str = Field(max_length=255)
    instructions: str
    owner_id: UUID
    emoji: str | None = None
    color: str | None = None
    sandbox: bool = False

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_COLORS:
            raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
        return v


class AgentUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    instructions: str | None = None
    emoji: str | None = None
    color: str | None = None
    description: str | None = None
    sandbox: bool | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_COLORS:
            raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
        return v


class AgentUserPermissionDB(SQLModel, table=True):
    __tablename__ = "agent_user_permissions"
    __table_args__ = (
        UniqueConstraint("agent_id", "user_id", name="uq_agent_user_permission"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    permission: PermissionLevel = Field(nullable=False)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class AgentPermissionRead(SQLModel):
    user_id: UUID
    permission: PermissionLevel


class AgentPermissionWrite(SQLModel):
    user_id: UUID
    permission: PermissionLevel


class AgentSubagentDB(SQLModel, table=True):
    __tablename__ = "agent_subagents"
    __table_args__ = (
        UniqueConstraint(
            "coordinator_id",
            "subagent_id",
            name="uq_agent_subagent",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    coordinator_id: UUID = Field(foreign_key="agents.id", nullable=False)
    subagent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class AgentSubagentRead(SQLModel):
    id: UUID
    coordinator_id: UUID
    subagent_id: UUID
    created_at: datetime
    updated_at: datetime


class SubagentRead(SQLModel):
    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None
    description: str | None = None


class AgentRead(SQLModel):
    id: UUID
    name: str
    instructions: str
    owner_id: UUID
    emoji: str | None
    color: str | None
    description: str | None
    sandbox: bool
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentMCPServerRead] | None = None
    subagents: list[SubagentRead] | None = None
    is_subagent: bool = False
    current_user_permission: str | None = None
