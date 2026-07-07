from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Enum as SAEnum
from sqlmodel import Column, Field, SQLModel, String, Text

# `state` is a leaf module (stdlib-only), so this cannot cycle even though
# `app.agents.runs` imports thread models elsewhere.
from app.agents.runs.state import RunStatus
from app.models import TimestampMixin


class ThreadSource(str, Enum):
    web = "web"
    slack = "slack"
    api = "api"
    trigger = "trigger"


# Sources considered first-party — surfaced in the user's personal thread list.
# Trigger threads are included: the owner follows (and approves HITL on) their
# scheduled runs from the sidebar, badged by `source` / `trigger_id`.
FIRST_PARTY_SOURCES: tuple[ThreadSource, ...] = (
    ThreadSource.web,
    ThreadSource.slack,
    ThreadSource.trigger,
)


class ThreadBase(SQLModel):
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    model_id: str | None = Field(default=None, nullable=True)
    first_message_content: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    source: ThreadSource = Field(
        default=ThreadSource.web,
        sa_column=Column(String, nullable=False, server_default=ThreadSource.web.value),
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
