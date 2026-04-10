from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.threads.models import ThreadBase


class ThreadCreate(SQLModel):
    id: str | None = None
    agent_id: UUID
    model_id: str | None = None
    first_message_content: str | None = None


class ThreadPatch(SQLModel):
    model_id: str | None = None
    first_message_content: str | None = None


class ThreadResponse(ThreadBase):
    id: str
    created_at: datetime
    updated_at: datetime
    agent_name: str | None = None
    agent_emoji: str | None = None
    agent_color: str | None = None
    agent_archived: bool = False
