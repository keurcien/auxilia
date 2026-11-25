from enum import StrEnum
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.visibility import ResourceVisibility


class ScopeResourceKind(StrEnum):
    agent = "agent"
    project = "project"
    trigger = "trigger"
    mcp_server = "mcp_server"
    skill = "skill"


class ScopeChangeRole(StrEnum):
    # The change the user asked for.
    target = "target"
    # Without it, the target change is rejected.
    required = "required"
    # Optional: shares what already relies on the target along with it.
    suggested = "suggested"


class ScopeChange(SQLModel):
    kind: ScopeResourceKind
    id: UUID
    visibility: ResourceVisibility
    team_ids: list[UUID] = Field(default_factory=list)


class ScopePlanItem(SQLModel):
    kind: ScopeResourceKind
    id: UUID
    name: str
    role: ScopeChangeRole
    depth: int
    reason: str | None = None
    can_manage: bool
    current_visibility: ResourceVisibility
    current_team_ids: list[UUID]
    visibility: ResourceVisibility
    team_ids: list[UUID]


class ScopePlanResponse(SQLModel):
    items: list[ScopePlanItem]
    # Why the requested change cannot be applied, even with its dependencies.
    blockers: list[str]
    # Set when the request was redirected, e.g. a trigger inheriting its
    # project's audience.
    note: str | None = None
    # The target plus every required change.
    minimal: list[ScopeChange]
    # `minimal` plus the suggestions; null when there is nothing to suggest.
    complete: list[ScopeChange] | None = None


class ScopeApplyRequest(SQLModel):
    changes: list[ScopeChange] = Field(min_length=1, max_length=200)
