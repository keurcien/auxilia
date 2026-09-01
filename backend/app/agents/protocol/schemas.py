"""Wire DTOs for the Agent Streaming Protocol endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ProtocolCommand(BaseModel):
    """One command envelope (`{id, method, params}`)."""

    id: int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class EventStreamBody(BaseModel):
    """`POST /threads/{id}/stream/events` body — the session's sink filter."""

    channels: list[str]
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    # Replay events with seq strictly greater than this. The stock client
    # never sends it on the SSE path (rotations replay from scratch), but the
    # protocol defines it, so honor it.
    since: int | None = None
