from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CallRequest(BaseModel):
    id: UUID
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
