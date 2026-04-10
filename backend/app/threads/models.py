from uuid import UUID, uuid4

from sqlmodel import Column, Field, SQLModel, String, Text

from app.models.mixins import TimestampMixin


class ThreadBase(SQLModel):
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    model_id: str | None = Field(default=None, nullable=True)
    first_message_content: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class ThreadDB(ThreadBase, TimestampMixin, table=True):
    __tablename__ = "threads"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        sa_column=Column(String, primary_key=True),
    )
