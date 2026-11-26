from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models import BaseDBModel


# Images of a chat gallery (`show_images`): readable like any thread artifact,
# but never listed as files nor restored into the execution sandbox.
GALLERY_ORIGIN = "gallery"


class ArtifactDB(BaseDBModel, table=True):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "thread_id",
            "tool_call_id",
            "source_path",
            name="uq_artifacts_workspace_thread_call_path",
        ),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id", ondelete="CASCADE", nullable=False, index=True
    )
    thread_id: str = Field(foreign_key="threads.id", ondelete="CASCADE", index=True)
    origin: str = Field(
        default="artifact", sa_column_kwargs={"server_default": "artifact"}
    )
    tool_call_id: str | None = None
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
