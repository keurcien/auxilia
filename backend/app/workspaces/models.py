from enum import Enum
from uuid import UUID

from sqlalchemy import LargeBinary
from sqlmodel import Column, Field, UniqueConstraint

from app.models import BaseDBModel


class WorkspaceRole(str, Enum):
    member = "member"
    editor = "editor"
    admin = "admin"


class WorkspaceDB(BaseDBModel, table=True):
    __tablename__ = "workspaces"

    name: str = Field(max_length=255, nullable=False)
    emoji: str | None = Field(default=None, max_length=10, nullable=True)
    color: str | None = Field(default=None, max_length=7, nullable=True)
    image_revision: UUID | None = Field(default=None, nullable=True)


class WorkspaceImageDB(BaseDBModel, table=True):
    __tablename__ = "workspace_images"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_image_workspace_id"),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    media_type: str = Field(max_length=50, nullable=False)
    sha256: str = Field(max_length=64, nullable=False)


class WorkspaceMembershipDB(BaseDBModel, table=True):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_membership_workspace_user",
        ),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    role: WorkspaceRole = Field(default=WorkspaceRole.member, nullable=False)
    team_id: UUID | None = Field(
        default=None,
        foreign_key="teams.id",
        ondelete="SET NULL",
        nullable=True,
    )
