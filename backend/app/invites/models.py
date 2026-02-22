from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Field, SQLModel


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class InviteDB(SQLModel, table=True):
    __tablename__ = "invites"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(max_length=255, index=True)
    role: str = Field(default="member", nullable=False)
    token: str = Field(unique=True, index=True)
    status: InviteStatus = Field(default=InviteStatus.pending, nullable=False)
    invited_by: UUID = Field(foreign_key="users.id", nullable=False)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
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
