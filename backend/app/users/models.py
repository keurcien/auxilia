from typing import TYPE_CHECKING, TypeVar, cast
from uuid import UUID

from pydantic import PrivateAttr
from sqlalchemy import JSON, Column, LargeBinary, String
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from app.models import BaseDBModel
from app.workspaces.models import WorkspaceRole


if TYPE_CHECKING:
    from app.workspaces.models import WorkspaceMembershipDB

T = TypeVar("T")


class UserBase(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255, unique=True, index=True)
    password_hash: str | None = Field(default=None)
    can_create_workspace: bool = Field(default=False, nullable=False)
    picture_url: str | None = Field(default=None, max_length=1024)
    image_revision: UUID | None = Field(default=None, nullable=True)
    two_factor_enabled: bool = Field(default=False, nullable=False)


class UserDB(UserBase, BaseDBModel, table=True):
    __tablename__ = "users"

    is_instance_owner: bool = Field(default=False, nullable=False)

    _workspace_role: WorkspaceRole = PrivateAttr(default=WorkspaceRole.member)
    _workspace_team_id: UUID | None = PrivateAttr(default=None)
    _active_workspace_id: UUID | None = PrivateAttr(default=None)

    oauth_accounts: list["OAuthAccountDB"] = Relationship(back_populates="user")

    def _private(self, name: str, default: T) -> T:
        # Rows loaded by SQLAlchemy bypass pydantic's ``__init__``, so
        # ``__pydantic_private__`` stays ``None`` until the first private
        # assignment; reading a PrivateAttr before that raises TypeError.
        private = self.__pydantic_private__
        if private is None:
            return default
        return cast(T, private.get(name, default))

    @property
    def role(self) -> WorkspaceRole:
        return self._private("_workspace_role", WorkspaceRole.member)

    @property
    def team_id(self) -> UUID | None:
        return self._private("_workspace_team_id", None)

    @property
    def active_workspace_id(self) -> UUID | None:
        return self._private("_active_workspace_id", None)

    def set_workspace_membership(self, membership: "WorkspaceMembershipDB") -> None:
        self._workspace_role = membership.role
        self._workspace_team_id = membership.team_id
        self._active_workspace_id = membership.workspace_id


class UserImageDB(BaseDBModel, table=True):
    __tablename__ = "user_images"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_image_user_id"),)

    user_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    media_type: str = Field(max_length=50, nullable=False)
    sha256: str = Field(max_length=64, nullable=False)


class UserTwoFactorDB(BaseDBModel, table=True):
    __tablename__ = "user_two_factors"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_two_factor_user_id"),)

    user_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    secret_encrypted: str = Field(sa_column=Column(String, nullable=False))
    backup_code_hashes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    last_used_totp_counter: int | None = Field(default=None, nullable=True)


class OAuthAccountBase(SQLModel):
    provider: str = Field(index=True)
    sub_id: str = Field(index=True)


class OAuthAccountDB(OAuthAccountBase, BaseDBModel, table=True):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "sub_id"),)

    user_id: UUID = Field(foreign_key="users.id", nullable=False)

    user: UserDB = Relationship(back_populates="oauth_accounts")
