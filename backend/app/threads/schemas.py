from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlmodel import SQLModel

from app.agents.runs.state import RunStatus
from app.threads.models import ThreadBase


class ThreadCreate(SQLModel):
    id: str | None = None
    agent_id: UUID
    model_id: str | None = None
    first_message_content: str | None = None


class ThreadPatch(SQLModel):
    # Rename only: the PATCH endpoint is a cosmetic rename of the thread's
    # display title. `model_id` is deliberately not patchable here — letting
    # callers set it to an arbitrary value would break later runs for the
    # thread ("Unknown model").
    first_message_content: str | None = None


class ThreadResponse(ThreadBase):
    id: str
    trigger_id: UUID | None = None
    # Outcome of the most recent run; None = no finished run. "busy" is
    # deliberately not a value here — in-flight state comes from the
    # /runs/active poll.
    last_run_status: RunStatus | None = None
    created_at: datetime
    updated_at: datetime
    agent_name: str | None = None
    agent_emoji: str | None = None
    agent_color: str | None = None
    agent_archived: bool = False


class AgentThreadResponse(ThreadResponse):
    user_email: str | None = None
    user_name: str | None = None


# Set when the requester is reading a thread they do not own but have admin
# access. Drives read-only mode on the chat page. `None` means the requester
# owns the thread (no special role).
ViewerRole = Literal["admin"]
