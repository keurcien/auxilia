from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# ORM Mixins
# ---------------------------------------------------------------------------


class UUIDMixin(SQLModel):
    """UUID primary key. Skip this for composite-key join tables."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)


class TimestampMixin(SQLModel):
    """Server-side created_at / updated_at timestamps."""

    # sqlmodel's Field stub types `sa_type` as `type[Any]`, but SQLModel accepts a
    # type *instance* (needed for DateTime(timezone=True)) — a stub inaccuracy, not
    # a real mismatch.
    created_at: datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
    updated_at: datetime = Field(  # type: ignore[call-overload]
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
