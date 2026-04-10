from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlmodel import Column, DateTime, Field, SQLModel

from app.models.mixins import BaseDBModel


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class InviteCreateDB(SQLModel):
    email: str
    role: str
    token: str
    invited_by: UUID
    expires_at: datetime


class InviteDB(BaseDBModel, table=True):
    __tablename__ = "invites"

    email: str = Field(max_length=255, index=True)
    role: str = Field(default="member", nullable=False)
    token: str = Field(unique=True, index=True)
    status: InviteStatus = Field(default=InviteStatus.pending, nullable=False)
    invited_by: UUID = Field(foreign_key="users.id", nullable=False)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
