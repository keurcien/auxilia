from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Field, SQLModel, Text


class ThreadBase(SQLModel):
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    model_id: str | None = Field(default=None, nullable=True)
    first_message_content: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class ThreadDB(ThreadBase, table=True):
    __tablename__ = "threads"

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


class ThreadCreate(SQLModel):
    agent_id: UUID
    model_id: str | None = None
    first_message_content: str | None = None


class ThreadUpdate(SQLModel):
    model_id: str | None = None
    first_message_content: str | None = None


class ThreadRead(ThreadBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
