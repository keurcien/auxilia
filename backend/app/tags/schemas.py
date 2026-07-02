from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel


class TagCreate(SQLModel):
    name: str


class TagPatch(SQLModel):
    name: str | None = None


class TagResponse(SQLModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
