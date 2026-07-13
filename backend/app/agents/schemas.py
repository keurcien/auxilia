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


class AgentCreateDB(SQLModel):
    name: str
    instructions: str
    owner_id: UUID
    emoji: str | None = None
    color: str | None = None
    description: str | None = None
    has_code_interpreter: bool = False

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
    has_code_interpreter: bool | None = None
    tag_id: UUID | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_COLORS:
            raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
        return v


class AgentMCPServerConfig(SQLModel):
    mcp_server_id: UUID
    tools: dict[str, ToolStatus] | None = None


class AgentConfig(SQLModel):
    """The whole agent config as one document — the payload of the unified
    PUT /agents/{id}/config save. Full replace semantics: `tools` is the
    complete per-tool map (or None = never synced), not a merge patch."""

    name: str
    instructions: str
    description: str | None = None
    emoji: str | None = None
    color: str | None = None
    has_code_interpreter: bool = False
    mcp_servers: list[AgentMCPServerConfig] = []
    subagent_ids: list[UUID] = []

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_COLORS:
            raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
        return v

    @field_validator("mcp_servers")
    @classmethod
    def validate_unique_servers(
        cls, v: list[AgentMCPServerConfig]
    ) -> list[AgentMCPServerConfig]:
        server_ids = [c.mcp_server_id for c in v]
        if len(server_ids) != len(set(server_ids)):
            raise ValueError("mcp_servers contains duplicate mcp_server_id entries")
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


class AgentTeamsSet(SQLModel):
    team_ids: list[UUID]


class AgentTeamsResponse(SQLModel):
    team_ids: list[UUID]


class AgentSubagentResponse(SQLModel):
    id: UUID
    supervisor_id: UUID
    subagent_id: UUID
    created_at: datetime
    updated_at: datetime


class SubagentResponse(SQLModel):
    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None
    description: str | None = None


class TagInfo(SQLModel):
    id: UUID
    name: str


class AgentOwnerInfo(SQLModel):
    id: UUID
    name: str | None = None
    email: str | None = None


class AgentResponse(SQLModel):
    id: UUID
    name: str
    instructions: str
    owner_id: UUID
    emoji: str | None
    color: str | None
    description: str | None
    has_code_interpreter: bool
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentMCPServerResponse] | None = None
    subagents: list[SubagentResponse] | None = None
    tag: TagInfo | None = None
    owner: AgentOwnerInfo | None = None
    is_subagent: bool = False
    current_user_permission: str | None = None
