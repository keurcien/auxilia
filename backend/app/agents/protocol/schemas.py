"""Wire DTOs for the Agent Streaming Protocol endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ProtocolCommand(BaseModel):
    """One command envelope (`{id, method, params}`)."""

    id: int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class HistoryBody(BaseModel):
    """`POST /threads/{id}/history` body (`client.threads.getHistory`).

    Only `checkpoint.checkpoint_ns` is honored: the client asks for one
    namespace's latest checkpoint to seed a subagent card. `before` and
    `metadata` are accepted so the stock client's body validates.
    """

    limit: int = Field(default=10, ge=1, le=100)
    before: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None

    @property
    def checkpoint_ns(self) -> str | None:
        ns = (self.checkpoint or {}).get("checkpoint_ns")
        return ns if isinstance(ns, str) and ns else None


class EventStreamBody(BaseModel):
    """`POST /threads/{id}/stream/events` body — the session's sink filter."""

    channels: list[str]
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    # Replay events with seq strictly greater than this. The stock client
    # never sends it on the SSE path (rotations replay from scratch), but the
    # protocol defines it, so honor it.
    since: int | None = None
