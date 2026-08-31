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
    """What a grant row can hold — the levels an admin can hand out."""

    member = "member"
    editor = "editor"
    admin = "admin"


class EffectivePermission(str, Enum):
    """A user's *resolved* access to one agent, ordered weakest → strongest.

    A superset of `PermissionLevel`: it adds `owner`, which no grant row can
    express because it is derived from `AgentDB.owner_id`. Ordering is what
    makes it worth having — "editor or better" was six hand-typed tuples
    across two layers before, and they had drifted (design review §4.4).
    Compare with `covers`, never with `<`: `str` already defines the
    comparison operators lexicographically, and "admin" < "editor" is true
    there.
    """

    member = "member"
    editor = "editor"
    admin = "admin"
    owner = "owner"

    def covers(self, at_least: "EffectivePermission") -> bool:
        """True when this permission is `at_least` or stronger."""
        return _PERMISSION_RANK[self] >= _PERMISSION_RANK[at_least]


_PERMISSION_RANK: dict[EffectivePermission, int] = {
    EffectivePermission.member: 0,
    EffectivePermission.editor: 1,
    EffectivePermission.admin: 2,
    EffectivePermission.owner: 3,
}


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


class AgentSandboxBase(SQLModel):
    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", nullable=False)
    # No cascade (consistent with agent_mcp_servers): deleting a bound
    # sandbox is refused; the admin explicitly detaches it from all agents
    # (DELETE /sandboxes/{id}?detach_agents=true). Threads are never bound
    # to a sandbox — only agents are.
    sandbox_id: UUID = Field(foreign_key="sandboxes.id", index=True, nullable=False)
    tools: dict[str, ToolStatus] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class AgentSandboxDB(AgentSandboxBase, BaseDBModel, table=True):
    __tablename__ = "agent_sandboxes"
    # One sandbox per agent for now: the deepagents runnable takes exactly one
    # execution backend. Kept as a link table (not a FK on agents) so the
    # binding carries per-agent config and the constraint can be relaxed later.
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_sandbox"),)


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
