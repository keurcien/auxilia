"""Tracks tool call state, deduplication, and normalization during streaming."""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrackedToolCall:
    """State for a single in-flight tool call."""

    tool_call_id: str
    name: str
    args_buffer: str = ""
    already_approved: bool = False
    index: int = 0


def make_tool_signature(name: str, args: dict | str) -> str:
    """
    Deterministic content signature for a tool call.

    Used to correlate tool calls across LLM-emit and LangGraph-execute phases,
    where IDs may not be preserved. Two calls with the same name and args
    will collide — this is intentional for dedup, but callers should be aware.
    """
    if isinstance(args, str):
        try:
            args_dict = json.loads(args) if args else {}
        except (json.JSONDecodeError, TypeError):
            args_dict = {"raw": args}
    else:
        args_dict = args or {}

    return f"{name}:{json.dumps(args_dict, sort_keys=True)}"


def normalize_tool_call(raw: Any) -> dict[str, Any]:
    """
    Normalize a tool call from either a dict or an object with attributes
    into a consistent dict shape.
    """
    if isinstance(raw, dict):
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "args": raw.get("args", {}),
            "index": raw.get("index", 0),
        }
    return {
        "id": getattr(raw, "id", None),
        "name": getattr(raw, "name", None),
        "args": getattr(raw, "args", {}),
        "index": getattr(raw, "index", 0),
    }


class ToolCallTracker:
    """
    Manages the lifecycle and deduplication of tool calls within a stream.

    Tracks two dimensions:
    - active_calls: tool calls currently in-flight (keyed by tool_call_id)
    - emitted_signatures: content-based dedup index (signature -> tool_call_id)
    """

    def __init__(self, pre_approved_ids: set[str] | None = None):
        self._active_calls: dict[str, TrackedToolCall] = {}
        self._emitted_signatures: dict[str, str] = {}
        self._pre_approved_ids: set[str] = pre_approved_ids or set()

    def is_pre_approved(self, tool_call_id: str) -> bool:
        return tool_call_id in self._pre_approved_ids

    def is_signature_emitted(self, signature: str) -> bool:
        return signature in self._emitted_signatures

    def is_active(self, tool_call_id: str) -> bool:
        return tool_call_id in self._active_calls

    def get_active(self, tool_call_id: str) -> TrackedToolCall | None:
        return self._active_calls.get(tool_call_id)

    def find_active_by_index(self, index: int) -> tuple[str, TrackedToolCall] | None:
        """Find an active tool call by its chunk index."""
        for tid, tracked in self._active_calls.items():
            if tracked.index == index:
                return tid, tracked
        return None

    def find_sole_active(self) -> tuple[str, TrackedToolCall] | None:
        """Return the only active call if exactly one exists."""
        if len(self._active_calls) == 1:
            tid = next(iter(self._active_calls))
            return tid, self._active_calls[tid]
        return None

    def register_signature(self, signature: str, tool_call_id: str) -> None:
        """Record that a tool with this signature has been emitted."""
        self._emitted_signatures[signature] = tool_call_id

    def resolve_id_for_signature(self, signature: str) -> str:
        """Get the tool_call_id for a signature, or generate a new one."""
        existing = self._emitted_signatures.get(signature)
        if existing:
            return existing
        new_id = str(uuid.uuid4())
        logger.debug(
            "Generated fallback ID %s for unseen signature: %s", new_id, signature)
        return new_id

    def start_call(
        self,
        tool_call_id: str,
        name: str,
        *,
        args_buffer: str = "",
        already_approved: bool = False,
        index: int = 0,
    ) -> TrackedToolCall:
        """Register a new active tool call."""
        tracked = TrackedToolCall(
            tool_call_id=tool_call_id,
            name=name,
            args_buffer=args_buffer,
            already_approved=already_approved,
            index=index,
        )
        self._active_calls[tool_call_id] = tracked
        logger.debug(
            "Started tool call %s (%s), approved=%s",
            tool_call_id, name, already_approved,
        )
        return tracked

    def finish_call(self, tool_call_id: str) -> TrackedToolCall | None:
        """Remove and return a completed tool call."""
        removed = self._active_calls.pop(tool_call_id, None)
        if removed:
            logger.debug("Finished tool call %s (%s)",
                         tool_call_id, removed.name)
        return removed

    def should_skip_emission(self, tool_call_id: str, signature: str) -> bool:
        """
        Check if a tool call should be silently skipped.

        Returns True if the tool was already emitted (by signature)
        or is currently active (by ID).
        """
        if signature in self._emitted_signatures:
            logger.debug(
                "Skipping duplicate tool (signature match): %s", signature)
            return True
        if tool_call_id in self._active_calls:
            logger.debug(
                "Skipping duplicate tool (already active): %s", tool_call_id)
            return True
        return False
