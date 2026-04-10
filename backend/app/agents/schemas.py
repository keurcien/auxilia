from datetime import datetime
from uuid import UUID

from pydantic import field_validator
from sqlmodel import SQLModel

from app.agents.models import (
    ALLOWED_COLORS,
    AgentMCPServerBase,
    PermissionLevel,
    ToolStatus,
)


class AgentCreate(SQLModel):
    name: str
    instructions: str
    emoji: str | None = None
    color: str | None = None
    sandbox: bool = False

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_COLORS:
            raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
        return v


class AgentCreateDB(SQLModel):
    name: str
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


class AgentPatch(SQLModel):
    name: str | None = None
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


class AgentMCPServerCreate(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerPatch(SQLModel):
    tools: dict[str, ToolStatus] | None = None


class AgentMCPServerResponse(AgentMCPServerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class AgentPermissionResponse(SQLModel):
    user_id: UUID
    permission: PermissionLevel


class AgentPermissionCreate(SQLModel):
    user_id: UUID
    permission: PermissionLevel


class AgentSubagentResponse(SQLModel):
    id: UUID
    coordinator_id: UUID
    subagent_id: UUID
    created_at: datetime
    updated_at: datetime


class SubagentResponse(SQLModel):
    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None
    description: str | None = None


class AgentResponse(SQLModel):
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
    mcp_servers: list[AgentMCPServerResponse] | None = None
    subagents: list[SubagentResponse] | None = None
    is_subagent: bool = False
    current_user_permission: str | None = None
