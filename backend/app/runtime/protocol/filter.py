"""Server-side event filtering for protocol stream sessions.

Mirrors the client's `subscription.js` matching semantics (channel set,
namespace prefixes with dynamic-suffix normalization, depth below prefix) so
the server's sink filter and the client's per-subscription narrowing can never
disagree about which events a session delivers.
"""

from dataclasses import dataclass

from app.runtime.protocol.events import infer_channel, namespace_matches


@dataclass(frozen=True)
class StreamFilter:
    channels: tuple[str, ...]
    namespaces: tuple[tuple[str, ...], ...] | None = None
    depth: int | None = None

    @classmethod
    def from_request(
        cls,
        channels: list[str],
        namespaces: list[list[str]] | None,
        depth: int | None,
    ) -> StreamFilter:
        return cls(
            channels=tuple(channels),
            namespaces=tuple(tuple(ns) for ns in namespaces)
            if namespaces is not None
            else None,
            depth=depth,
        )

    def matches(self, event: dict) -> bool:
        channel = infer_channel(event)
        if channel is None:
            return False
        if not (
            channel in self.channels
            or (channel.startswith("custom:") and "custom" in self.channels)
        ):
            return False
        namespace = event.get("params", {}).get("namespace", [])
        prefixes = [list(ns) for ns in self.namespaces] if self.namespaces else None
        return namespace_matches(namespace, prefixes, self.depth)


@dataclass(frozen=True)
class AnyFilter:
    """Delivers an event when any of its filters would."""

    filters: tuple[StreamFilter, ...]

    def matches(self, event: dict) -> bool:
        return any(f.matches(event) for f in self.filters)


def run_stream_filter(channels: list[str], *, subagents: bool) -> AnyFilter:
    """The sink of `POST /threads/{id}/runs/stream`.

    Without `subagents` only the root agent's events pass — a consumer that
    appends every text delta to one bubble must not interleave a subagent's
    prose with the answer.

    `input` passes whatever was asked for, from every namespace: dropping an
    approval request leaves the caller with an `interrupted` run and nothing
    to answer, and a paused subagent's request is announced under *its*
    namespace (see `ProtocolEmitter._input_requested`)."""
    rest = tuple(c for c in channels if c != "input")
    return AnyFilter(
        (
            StreamFilter(channels=("input",)),
            StreamFilter(channels=rest)
            if subagents
            else StreamFilter(channels=rest, namespaces=((),), depth=0),
        )
    )
