import re
from datetime import datetime
from uuid import UUID

from pydantic import field_validator
from sqlmodel import SQLModel


def _validate_color(v: str | None) -> str | None:
    if v is not None and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) is None:
        raise ValueError("color must be a valid hex color (for example, #0984E3)")
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
