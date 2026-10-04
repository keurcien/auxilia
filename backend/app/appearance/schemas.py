from uuid import UUID

from pydantic import BaseModel, Field


class InstanceAppearanceResponse(BaseModel):
    app_name: str
    logo_revision: UUID | None = None


class InstanceAppearancePatch(BaseModel):
    app_name: str = Field(min_length=1, max_length=50)
