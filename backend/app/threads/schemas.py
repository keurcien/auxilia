from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Field, SQLModel

from app.runtime.runs.state import RunStatus
from app.threads.models import ThreadBase, ThreadToolMode


class ThreadCreate(SQLModel):
    id: str | None = None
    agent_id: UUID
    project_id: UUID | None = None
    folder_id: UUID | None = None
    model_id: str | None = None
    # Validated against the model's whitelist-declared levels at creation
    # (400 on an undeclared value). None = the model's default.
    reasoning_effort: str | None = None
    first_message_content: str | None = None
    # None inherits the agent's discovery mode.
    tool_mode: ThreadToolMode | None = None
    memories_enabled: bool = True
    disabled_mcp_server_ids: list[UUID] = Field(default_factory=list)
    disabled_skill_ids: list[UUID] = Field(default_factory=list)
    disabled_sandbox_ids: list[UUID] = Field(default_factory=list)
    disabled_subagent_ids: list[UUID] = Field(default_factory=list)
    disabled_mcp_tools: dict[UUID, list[str]] = Field(default_factory=dict)


class ThreadStartCreate(BaseModel):
    """Create a web thread and its first durable run in one transaction."""

    thread: ThreadCreate
    project_id: UUID | None = None
    folder_id: UUID | None = None
    message_text: str = PydanticField(default="", max_length=100_000)
    include_images: bool = True
    store_files: bool = False


class ThreadPatch(SQLModel):
    # Rename only: the PATCH endpoint is a cosmetic rename of the thread's
    # display title. Model changes use their own validated endpoint.
    first_message_content: str | None = None


class ThreadModelUpdate(SQLModel):
    model_id: str = Field(max_length=255)
    # Validated against the model's whitelist-declared levels (400 on an
    # undeclared value). None = the model's default — so a bare model change
    # drops any effort chosen for the previous model.
    reasoning_effort: str | None = Field(default=None, max_length=32)


class ThreadMemoriesUpdate(SQLModel):
    memories_enabled: bool


class ThreadPlacementUpdate(SQLModel):
    project_id: UUID | None = None
    folder_id: UUID | None = None


ThreadPlacementFilter = Literal["all", "assigned", "unassigned"]


class ThreadBulkPlacementUpdate(BaseModel):
    thread_ids: list[str] = PydanticField(min_length=1, max_length=200)
    project_id: UUID | None = None
    folder_id: UUID | None = None


class ThreadPlacementResult(SQLModel):
    thread_id: str
    previous_project_id: UUID | None = None
    previous_folder_id: UUID | None = None
    project_id: UUID | None = None
    folder_id: UUID | None = None


class ThreadBulkPlacementResponse(SQLModel):
    items: list[ThreadPlacementResult] = Field(default_factory=list)


class ThreadCompletionUpdate(SQLModel):
    completed: bool


class ThreadResourcesPatch(SQLModel):
    # Conversation-level tool policy, updated with the other capability
    # choices so the composer has one persistence path.
    tool_mode: ThreadToolMode | None = None
    disabled_mcp_server_ids: list[UUID] = Field(default_factory=list)
    disabled_skill_ids: list[UUID] = Field(default_factory=list)
    disabled_sandbox_ids: list[UUID] = Field(default_factory=list)
    disabled_subagent_ids: list[UUID] = Field(default_factory=list)
    disabled_mcp_tools: dict[UUID, list[str]] = Field(default_factory=dict)


class ThreadResponse(ThreadBase):
    id: str
    trigger_id: UUID | None = None
    project_id: UUID | None = None
    folder_id: UUID | None = None
    completed_at: datetime | None = None
    # Outcome of the most recent run; None = no finished run. "busy" is
    # deliberately not a value here — in-flight state comes from the
    # /runs/active poll.
    last_run_status: RunStatus | None = None
    created_at: datetime
    updated_at: datetime
    agent_name: str | None = None
    agent_emoji: str | None = None
    agent_color: str | None = None
    agent_image_revision: UUID | None = None
    agent_archived: bool = False
    # Whether the thread's current model can run right now (whitelist ∧
    # provider key ∧ admin-enabled). Server-computed on the single-thread GET
    # so the frontend can disable the composer without re-deriving the rule;
    # list endpoints leave the default (the composer only exists on the
    # thread page).
    model_available: bool = True
    disabled_mcp_server_ids: list[UUID] = Field(default_factory=list)
    disabled_skill_ids: list[UUID] = Field(default_factory=list)
    disabled_sandbox_ids: list[UUID] = Field(default_factory=list)
    disabled_subagent_ids: list[UUID] = Field(default_factory=list)


class AgentThreadResponse(ThreadResponse):
    user_email: str | None = None
    user_name: str | None = None


# Set when the requester is reading a thread they do not own but have admin
# access. Drives read-only mode on the chat page. `None` means the requester
# owns the thread (no special role).
ViewerRole = Literal["admin", "viewer"]
