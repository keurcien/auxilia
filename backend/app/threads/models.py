from enum import Enum
from uuid import UUID, uuid4

from sqlmodel import Column, Field, SQLModel, String, Text

from app.models import TimestampMixin


class ThreadSource(str, Enum):
    web = "web"
    slack = "slack"
    api = "api"


# Sources considered first-party — surfaced in the user's personal thread list.
FIRST_PARTY_SOURCES: tuple[ThreadSource, ...] = (ThreadSource.web, ThreadSource.slack)


class ThreadBase(SQLModel):
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)
    model_id: str | None = Field(default=None, nullable=True)
    first_message_content: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    source: ThreadSource = Field(
        default=ThreadSource.web,
        sa_column=Column(String, nullable=False, server_default=ThreadSource.web.value),
    )


class ThreadDB(ThreadBase, TimestampMixin, table=True):
    __tablename__ = "threads"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        sa_column=Column(String, primary_key=True),
    )
