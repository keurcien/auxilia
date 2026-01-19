from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Field, Relationship, SQLModel, UniqueConstraint


class UserBase(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255, unique=True, index=True)
    hashed_password: str | None = Field(default=None)
    is_superuser: bool = Field(default=False, nullable=False)


class UserDB(UserBase, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )

    oauth_accounts: list["OAuthAccountDB"] = Relationship(back_populates="user")


class UserCreate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    hashed_password: str | None = None
    is_superuser: bool = False


class UserUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    hashed_password: str | None = None
    is_superuser: bool | None = None


class UserRead(SQLModel):
    id: UUID
    name: str | None
    email: str | None
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


class OAuthAccountBase(SQLModel):
    provider: str = Field(index=True)
    sub_id: str = Field(index=True)


class OAuthAccountDB(OAuthAccountBase, table=True):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "sub_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )

    user: UserDB = Relationship(back_populates="oauth_accounts")


class OAuthAccountCreate(SQLModel):
    provider: str
    sub_id: str
    user_id: UUID


class OAuthAccountRead(OAuthAccountBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
