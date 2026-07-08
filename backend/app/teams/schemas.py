from datetime import datetime
from uuid import UUID

from pydantic import field_validator
from sqlmodel import SQLModel

from app.agents.models import ALLOWED_COLORS


def _validate_color(v: str | None) -> str | None:
    if v is not None and v not in ALLOWED_COLORS:
        raise ValueError(f"color must be one of {sorted(ALLOWED_COLORS)}")
    return v


class TeamCreate(SQLModel):
    name: str
    color: str | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return _validate_color(v)


class TeamPatch(SQLModel):
    name: str | None = None
    color: str | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return _validate_color(v)


class TeamResponse(SQLModel):
    id: UUID
    name: str
    color: str | None
    # Populated by TeamService.list; endpoints returning a single team leave
    # it at 0 (create/update responses don't need it).
    member_count: int = 0
    created_at: datetime
    updated_at: datetime
