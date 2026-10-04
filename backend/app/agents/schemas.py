import re
from datetime import datetime
from uuid import UUID

from pydantic import field_validator
from sqlmodel import SQLModel

from app.agents.models import (
    AgentMCPServerBase,
    EffectivePermission,
    PermissionLevel,
    ToolStatus,
)
from app.sandbox.models import SandboxProviderType
from app.skills.schemas import AgentSkillResponse


def _normalize_group(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "/".join(part.strip() for part in value.split("/") if part.strip())
    if not normalized:
        return None
    if len(normalized) > 255:
        raise ValueError("group must be at most 255 characters")
    return normalized


def _normalize_color(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if re.fullmatch(r"#[0-9A-F]{6}", normalized) is None:
        raise ValueError("color must be a six-digit hex value")
    return normalized


class AgentCreateDB(SQLModel):
    workspace_id: UUID
    name: str
    instructions: str
    owner_id: UUID
    emoji: str | None = None
    color: str | None = None
    description: str | None = None
    group: str | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return _normalize_color(v)


class AgentPatch(SQLModel):
    name: str | None = None
    instructions: str | None = None
    emoji: str | None = None
    color: str | None = None
    description: str | None = None
    group: str | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return _normalize_color(v)

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)


class AgentMCPServerConfig(SQLModel):
    mcp_server_id: UUID
    tools: dict[str, ToolStatus] | None = None


class AgentSandboxConfig(SQLModel):
    sandbox_id: UUID
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
    group: str | None = None
    mcp_servers: list[AgentMCPServerConfig] = []
    sandboxes: list[AgentSandboxConfig] = []
    subagent_ids: list[UUID] = []
    # Skills enabled on the agent — whole-set, like the other bindings.
    skill_ids: list[UUID] = []

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)

    @field_validator("sandboxes")
    @classmethod
    def validate_single_sandbox(
        cls, v: list[AgentSandboxConfig]
    ) -> list[AgentSandboxConfig]:
        # The deepagents runnable takes exactly one execution backend; the
        # field stays list-shaped so the API is stable if that changes.
        if len(v) > 1:
            raise ValueError("an agent can bind at most one sandbox")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return _normalize_color(v)

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


class AgentMCPServerListResponse(SQLModel):
    """Slim binding for list responses — identifies the server without the
    per-tool map, which only the agent detail/editor flow consumes."""

    id: UUID
    agent_id: UUID
    mcp_server_id: UUID
    created_at: datetime
    updated_at: datetime


class AgentMCPServerResponse(AgentMCPServerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class AgentSandboxResponse(SQLModel):
    """One agent↔sandbox binding, flattened with the sandbox's display
    fields so the editor never joins client-side."""

    sandbox_id: UUID
    tools: dict[str, ToolStatus] | None = None
    name: str
    provider: SandboxProviderType
    url: str


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
    image_revision: UUID | None = None
    description: str | None = None


class AgentOwnerInfo(SQLModel):
    id: UUID
    name: str | None = None
    email: str | None = None
    picture_url: str | None = None
    image_revision: UUID | None = None


class AgentListResponse(SQLModel):
    """List-row projection: everything the agents list and pickers render.

    Omits the heavyweight fields — ``instructions`` (agent prompts run to
    tens of KB each) and the bindings' per-tool maps — which only the detail
    endpoint returns. GET /agents/ serializes through this schema; the
    service still assembles full ``AgentResponse`` objects internally.
    """

    id: UUID
    name: str
    owner_id: UUID
    emoji: str | None
    color: str | None
    image_revision: UUID | None = None
    description: str | None
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentMCPServerListResponse] | None = None
    subagents: list[SubagentResponse] | None = None
    group: str | None = None
    owner: AgentOwnerInfo | None = None
    is_subagent: bool = False
    current_user_permission: EffectivePermission | None = None


class AgentResponse(AgentListResponse):
    instructions: str
    mcp_servers: list[AgentMCPServerResponse] | None = None
    # Sandboxes ride only on the full response: the runtime and the agent
    # editor consume the binding; list rows never render it.
    sandboxes: list[AgentSandboxResponse] | None = None
    # Skills too: the editor's selection and the runtime's catalog source.
    skills: list[AgentSkillResponse] | None = None
