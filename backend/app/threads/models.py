from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum as SAEnum, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, String, Text

from app.models import TimestampMixin

# `state` is a leaf module (stdlib-only), so this cannot cycle even though
# `app.runtime.runs` imports thread models elsewhere.
from app.runtime.runs.state import RunStatus


class ThreadSource(str, Enum):
    web = "web"
    slack = "slack"
    telegram = "telegram"
    whatsapp = "whatsapp"
    api = "api"
    trigger = "trigger"


class ThreadToolMode(str, Enum):
    """Conversation-level tool policy.

    NULL on the thread means "inherit the agent's discovery mode". The named
    discovery modes override it for this conversation. Eager and Precision
    respect the thread's resource selections; Lazy and Force all force-enable
    every attached capability, while No tools removes them all.
    """

    no_tools = "no_tools"
    eager = "eager"
    lazy = "lazy"
    precision = "precision"
    force_all = "force_all"

    @property
    def force_enable_all_capabilities(self) -> bool:
        """Whether this mode ignores resource exclusions and agent defaults."""
        return self in {ThreadToolMode.lazy, ThreadToolMode.force_all}


# Sources considered first-party — surfaced in the user's personal thread list.
# Trigger threads are included: the owner follows (and approves HITL on) their
# scheduled runs from the sidebar, badged by `source` / `trigger_id`.
FIRST_PARTY_SOURCES: tuple[ThreadSource, ...] = (
    ThreadSource.web,
    ThreadSource.slack,
    ThreadSource.telegram,
    ThreadSource.whatsapp,
    ThreadSource.trigger,
)


def _json_list_column() -> Column:
    return Column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        server_default=text("'[]'"),
    )


def _json_object_column() -> Column:
    return Column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        server_default=text("'{}'"),
    )


class ThreadBase(SQLModel):
    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    model_id: str | None = Field(default=None, nullable=True)
    # The user's reasoning-effort choice for the current model, one of the
    # whitelist entry's declared levels. NULL = no explicit choice — the
    # model runs on its default path. Changing model resets this choice.
    reasoning_effort: str | None = Field(default=None, nullable=True)
    first_message_content: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    source: ThreadSource = Field(
        default=ThreadSource.web,
        sa_column=Column(String, nullable=False, server_default=ThreadSource.web.value),
    )
    tool_mode: ThreadToolMode | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                ThreadToolMode,
                native_enum=False,
                create_constraint=False,
                length=16,
            ),
            nullable=True,
        ),
    )
    memories_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )


class ThreadDB(ThreadBase, TimestampMixin, table=True):
    __tablename__ = "threads"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        sa_column=Column(String, primary_key=True),
    )
    # Set only on trigger-sourced threads — links each firing back to its
    # trigger for the run-history view. Survives trigger deletion (SET NULL).
    trigger_id: UUID | None = Field(
        default=None,
        foreign_key="triggers.id",
        ondelete="SET NULL",
        index=True,
        nullable=True,
    )
    project_id: UUID | None = Field(
        default=None,
        foreign_key="projects.id",
        ondelete="SET NULL",
        index=True,
        nullable=True,
    )
    folder_id: UUID | None = Field(
        default=None,
        foreign_key="project_folders.id",
        ondelete="SET NULL",
        index=True,
        nullable=True,
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # The sandbox every run of this thread reconnects to. Stamped by the
    # runtime when a run creates one (and again when a gone sandbox is
    # replaced); NULL until then, or for agents without a sandbox binding.
    # Server-side only — not in ThreadResponse.
    sandbox_id: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    # Which sandbox row issued `sandbox_id`. An agent rebound to a different
    # sandbox would otherwise hand the old provider's id to the new one, which
    # cannot know it: the run failed instead of starting a fresh sandbox.
    sandbox_source_id: UUID | None = Field(
        default=None, foreign_key="sandboxes.id", ondelete="SET NULL", nullable=True
    )
    # Conversation-level capability narrowing. Deny lists preserve the agent's
    # defaults for existing threads and automatically enable resources attached
    # to the graph later.
    disabled_mcp_server_ids: list[str] = Field(
        default_factory=list, sa_column=_json_list_column()
    )
    disabled_skill_ids: list[str] = Field(
        default_factory=list, sa_column=_json_list_column()
    )
    disabled_sandbox_ids: list[str] = Field(
        default_factory=list, sa_column=_json_list_column()
    )
    disabled_subagent_ids: list[str] = Field(
        default_factory=list, sa_column=_json_list_column()
    )
    disabled_mcp_tools: dict[str, list[str]] = Field(
        default_factory=dict, sa_column=_json_object_column()
    )
    # Terminal status of the thread's most recent run, stamped in the same
    # transaction as the run's terminal update. NULL = no finished run
    # recorded. Server-stamped only — deliberately not on ThreadBase so it
    # can't arrive through create/patch payloads. Non-native enum (plain
    # VARCHAR in the DB) so rows load back as RunStatus members.
    last_run_status: RunStatus | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(RunStatus, native_enum=False, create_constraint=False),
            nullable=True,
        ),
    )
    # Monotonic allocator for durable prompt ordering. Positions belong to
    # pending RunDB rows; keeping the counter on the thread makes allocation
    # atomic without scanning the queue.
    prompt_queue_counter: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default="0"),
    )
    # An interrupted run has released the per-thread running mutex, but normal
    # prompts must remain parked until an input.respond run resumes it.
    awaiting_input: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # A short renewable lease pauses ordinary prompt dispatch while the user
    # edits one queued item. Expiry prevents an abandoned browser tab from
    # blocking the conversation indefinitely.
    queue_edit_run_id: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    queue_edit_expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
