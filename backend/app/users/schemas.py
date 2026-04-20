from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.users.models import OAuthAccountBase, WorkspaceRole


class UserCreate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    hashed_password: str | None = None
    role: WorkspaceRole = WorkspaceRole.member


class UserPatch(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    hashed_password: str | None = None


class UserRolePatch(SQLModel):
    role: WorkspaceRole


class UserResponse(SQLModel):
    id: UUID
    name: str | None
    email: str | None
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime


class OAuthAccountCreate(SQLModel):
    provider: str
    sub_id: str
    user_id: UUID


class OAuthAccountResponse(OAuthAccountBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
