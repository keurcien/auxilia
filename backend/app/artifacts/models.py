from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models import BaseDBModel


class ArtifactDB(BaseDBModel, table=True):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("thread_id", "tool_call_id", "source_path"),)

    thread_id: str = Field(foreign_key="threads.id", ondelete="CASCADE", index=True)
    tool_call_id: str
    source_path: str
    title: str
    filename: str
    mime_type: str
    size: int
    sha256: str
    storage_kind: str
    storage_key: str
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    sandbox_source_id: UUID | None = Field(
        default=None, foreign_key="sandboxes.id", ondelete="SET NULL"
    )
    sandbox_id: str | None = None
