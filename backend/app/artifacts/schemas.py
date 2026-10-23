from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PresentFile(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=200)


class ArtifactResponse(BaseModel):
    id: UUID
    thread_id: str
    origin: str
    tool_call_id: str | None
    title: str
    filename: str
    mime_type: str
    size: int
    # Changes when the content changes: the viewer's reload signal and the
    # If-Match revision for edits.
    sha256: str
    temporary: bool
    created_at: datetime | None


class ArtifactViewerResponse(BaseModel):
    html_sources: list[str]
