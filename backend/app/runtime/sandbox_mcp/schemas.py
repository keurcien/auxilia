from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CallRequest(BaseModel):
    id: UUID
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    phase: UUID
    type: Literal["approve", "reject", "reconnect"]
