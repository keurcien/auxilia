from enum import Enum
from uuid import UUID

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from app.models.mixins import BaseDBModel


class WorkspaceRole(str, Enum):
    member = "member"
    editor = "editor"
    admin = "admin"


class UserBase(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255, unique=True, index=True)
    hashed_password: str | None = Field(default=None)
    role: WorkspaceRole = Field(default=WorkspaceRole.member, nullable=False)


class UserDB(UserBase, BaseDBModel, table=True):
    __tablename__ = "users"

    oauth_accounts: list["OAuthAccountDB"] = Relationship(back_populates="user")


class OAuthAccountBase(SQLModel):
    provider: str = Field(index=True)
    sub_id: str = Field(index=True)


class OAuthAccountDB(OAuthAccountBase, BaseDBModel, table=True):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "sub_id"),)

    user_id: UUID = Field(foreign_key="users.id", nullable=False)

    user: UserDB = Relationship(back_populates="oauth_accounts")
