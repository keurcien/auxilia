import re
from datetime import datetime
from uuid import UUID

from pydantic import field_validator
from sqlmodel import Field, SQLModel

from app.workspaces.models import WorkspaceRole


def _normalize_color(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if re.fullmatch(r"#[0-9A-F]{6}", normalized) is None:
        raise ValueError("color must be a six-digit hex value")
    return normalized


class WorkspaceCreate(SQLModel):
    name: str = Field(max_length=255)
    emoji: str | None = Field(default=None, max_length=10)
    color: str | None = Field(default=None, max_length=7)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        return _normalize_color(value)


class WorkspacePatch(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    emoji: str | None = Field(default=None, max_length=10)
    color: str | None = Field(default=None, max_length=7)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        return _normalize_color(value)


class WorkspaceDelete(SQLModel):
    name: str = Field(max_length=255)


class WorkspaceDeleteResponse(SQLModel):
    active_workspace_id: UUID | None = None


class WorkspaceResponse(SQLModel):
    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None
    image_revision: UUID | None = None
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime
