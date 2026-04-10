from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel


class UUIDMixin(SQLModel):
    """UUID primary key. Skip this for composite-key join tables."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)


class TimestampMixin(SQLModel):
    """Server-side created_at / updated_at timestamps."""

    created_at: datetime = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
    updated_at: datetime = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
            "nullable": False,
        },
    )


class BaseDBModel(UUIDMixin, TimestampMixin, SQLModel):
    """Standard base for most models: UUID PK + timestamps."""

    pass
