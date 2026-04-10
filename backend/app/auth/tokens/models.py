from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Field, SQLModel


class PersonalAccessTokenDB(SQLModel, table=True):
    __tablename__ = "personal_access_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(max_length=255, nullable=False)
    token_hash: str = Field(nullable=False)
    prefix: str = Field(max_length=12, nullable=False, index=True)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
