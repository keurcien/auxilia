from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PresentFile(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=200)


class ArtifactResponse(BaseModel):
    id: UUID
    thread_id: str
    tool_call_id: str
    title: str
    filename: str
    mime_type: str
    size: int
    temporary: bool
    created_at: datetime | None
