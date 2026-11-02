from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, DateTime, Text
from sqlmodel import Field, UniqueConstraint

from app.models import BaseDBModel


class WorkspaceAuthenticationDB(BaseDBModel, table=True):
    __tablename__ = "workspace_authentication"
    __table_args__ = (
        CheckConstraint(
            "(google_client_id_encrypted IS NULL) = "
            "(google_client_secret_encrypted IS NULL)",
            name="ck_workspace_authentication_google_pair",
        ),
        UniqueConstraint(
            "workspace_id",
            "key",
            name="uq_workspace_authentication_workspace_key",
        ),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    key: str = Field(default="default", nullable=False)
    enabled: bool = Field(default=False, nullable=False)
    google_client_id_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    google_client_secret_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    google_exclusive: bool = Field(default=False, nullable=False)
    enforce_two_factor: bool = Field(default=False, nullable=False)


class PasswordResetTokenDB(BaseDBModel, table=True):
    __tablename__ = "password_reset_tokens"

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    token_hash: str = Field(max_length=64, nullable=False, unique=True, index=True)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
