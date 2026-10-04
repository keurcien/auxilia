from datetime import datetime
from uuid import UUID

from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel

from app.users.models import OAuthAccountBase, WorkspaceRole


class UserCreate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    password_hash: str | None = None
    role: WorkspaceRole = WorkspaceRole.member


class UserCreateDB(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    password_hash: str | None = None


class UserPatch(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    password_hash: str | None = None
    can_create_workspace: bool | None = None


class UserRolePatch(SQLModel):
    role: WorkspaceRole


class UserTeamPatch(SQLModel):
    team_id: UUID | None = None


class UserResponse(SQLModel):
    id: UUID
    name: str | None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None
    is_instance_owner: bool = False
    role: WorkspaceRole
    team_id: UUID | None = None
    can_create_workspace: bool = False
    picture_url: str | None = None
    image_revision: UUID | None = None
    created_at: datetime
    updated_at: datetime


class CurrentUserResponse(UserResponse):
    workspace_id: UUID | None = None
    two_factor_enabled: bool = False


class ProfilePatch(SQLModel):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)


class PasswordChange(SQLModel):
    current_password: str | None = None
    new_password: str = PydanticField(min_length=8, max_length=128)


class TwoFactorStatus(SQLModel):
    enabled: bool
    backup_codes_remaining: int = 0


class TwoFactorSetupRequest(SQLModel):
    current_password: str | None = None


class TwoFactorSetupResponse(SQLModel):
    secret: str
    otpauth_uri: str
    qr_code_data_url: str
    setup_token: str


class TwoFactorConfirmRequest(SQLModel):
    setup_token: str
    code: str


class TwoFactorDisableRequest(SQLModel):
    current_password: str | None = None
    code: str


class TwoFactorRegenerateRequest(SQLModel):
    current_password: str | None = None
    code: str


class BackupCodesResponse(SQLModel):
    backup_codes: list[str]


class UserRoleCounts(SQLModel):
    """Workspace-wide user counts, total and per role (drives filter chips)."""

    total: int
    member: int = 0
    editor: int = 0
    admin: int = 0


class OAuthAccountCreate(SQLModel):
    provider: str
    sub_id: str
    user_id: UUID


class OAuthAccountResponse(OAuthAccountBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
