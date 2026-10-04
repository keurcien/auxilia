from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models import BaseDBModel


class WorkspaceObservabilityDB(BaseDBModel, table=True):
    __tablename__ = "workspace_observability"
    __table_args__ = (
        CheckConstraint(
            "(public_key_encrypted IS NULL) = (secret_key_encrypted IS NULL)",
            name="ck_workspace_observability_credentials_pair",
        ),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="ck_workspace_observability_timeout",
        ),
        UniqueConstraint("workspace_id", "key", name="uq_observability_workspace_key"),
    )

    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    key: str = Field(default="default", nullable=False)
    enabled: bool = Field(default=False, nullable=False)
    base_url: str = Field(default="https://cloud.langfuse.com", max_length=2048)
    public_key_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    secret_key_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    timeout_seconds: int = Field(default=15, ge=1, le=120, nullable=False)
