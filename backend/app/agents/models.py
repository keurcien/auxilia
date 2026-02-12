from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Field, SQLModel, Text


class ToolStatus(str, Enum):
    always_allow = "always_allow"
    needs_approval = "needs_approval"
    disabled = "disabled"


class AgentMCPServer(BaseModel):
    id: UUID
    tools: dict[str, ToolStatus] | None = None


class AgentConfig(BaseModel):
    name: str
    model: str
    instructions: str
    mcp_servers: list[AgentMCPServer]


# Agent MCP Server Binding Models (Database)
class AgentMCPServerBindingBase(SQLModel):
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False)
    tools: dict[str, ToolStatus] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class AgentMCPServerBindingDB(AgentMCPServerBindingBase, table=True):
    __tablename__ = "agent_mcp_server_bindings"

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


class AgentMCPServerBindingCreate(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerBindingUpdate(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerBindingRead(AgentMCPServerBindingBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


# Agent Models (Database)
class AgentBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    instructions: str = Field(sa_column=Column(Text, nullable=False))
    owner_id: UUID = Field(foreign_key="users.id", nullable=False)
    emoji: str | None = Field(default=None, max_length=10, nullable=True)


class AgentDB(AgentBase, table=True):
    __tablename__ = "agents"

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


class AgentCreate(SQLModel):
    name: str = Field(max_length=255)
    instructions: str
    owner_id: UUID
    emoji: str | None = None


class AgentUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    instructions: str | None = None
    emoji: str | None = None


class AgentRead(SQLModel):
    id: UUID
    name: str
    instructions: str
    owner_id: UUID
    emoji: str | None
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentMCPServer] | None = None
