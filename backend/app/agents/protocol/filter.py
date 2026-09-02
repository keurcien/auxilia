"""Server-side event filtering for protocol stream sessions.

Mirrors the client's `subscription.js` matching semantics (channel set,
namespace prefixes with dynamic-suffix normalization, depth below prefix) so
the server's sink filter and the client's per-subscription narrowing can never
disagree about which events a session delivers.
"""

from dataclasses import dataclass

from app.agents.protocol.events import infer_channel, namespace_matches


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
    ) -> "StreamFilter":
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
