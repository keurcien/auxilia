"""Protocol event vocabulary — builders and channel/namespace helpers.

Shapes mirror `@langchain/protocol`'s `protocol.ts` (the client's source of
truth). Every builder returns the *event data* `{method, params}`; the stream
layer wraps it into the wire envelope `{type: "event", event_id, seq, ...}`
when it stamps replay cursors.

Channel inference and namespace prefix matching mirror the client's
`subscription.js` (`inferChannel` / `isPrefixMatch`) so server-side filtering
and the client's per-subscription narrowing can never disagree.
"""

import time
from typing import Any


Namespace = list[str]

#: Channels a subscription may request. `custom:<name>` is matched by prefix.
KNOWN_CHANNELS = {
    "values",
    "updates",
    "messages",
    "tools",
    "lifecycle",
    "input",
    "checkpoints",
    "tasks",
    "custom",
}


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def _params(namespace: Namespace, data: Any, node: str | None = None) -> dict:
    params: dict[str, Any] = {
        "namespace": namespace,
        "timestamp": timestamp_ms(),
        "data": data,
    }
    if node is not None:
        params["node"] = node
    return params


# --- lifecycle ---------------------------------------------------------------


#: Protocol `AgentStatus` values a lifecycle event may carry.
AGENT_STATUSES = frozenset({"started", "running", "completed", "failed", "interrupted"})

#: `RunStatus.value` → protocol AgentStatus for the terminal root lifecycle
#: event. `cancelled` maps to completed: a user Stop is not a failure, and the
#: protocol has no cancelled status. Anything unlisted (a newer producer
#: mid-deploy) is reported as `failed` — never as a false `completed`.
TERMINAL_STATUS: dict[str, str] = {
    "success": "completed",
    "interrupted": "interrupted",
    "error": "failed",
    "timeout": "failed",
    "cancelled": "completed",
}


def lifecycle_event(
    namespace: Namespace,
    status: str,
    *,
    error: str | None = None,
    graph_name: str | None = None,
    cause: dict | None = None,
) -> dict:
    """`lifecycle` event: status ∈ started|running|completed|failed|interrupted.

    `graph_name` and `cause` (`{"type": "toolCall", "tool_call_id": …}`) are
    the subagent linkage the spec defines for namespaced `started` events."""
    data: dict[str, Any] = {"event": status}
    if graph_name is not None:
        data["graph_name"] = graph_name
    if cause is not None:
        data["cause"] = cause
    if error is not None:
        data["error"] = error
    return {"method": "lifecycle", "params": _params(namespace, data)}


def terminal_lifecycle(run_status: str | None, *, error: str | None = None) -> dict:
    """The root lifecycle event that ends a run, from its `RunStatus.value`.

    `run_status=None` means the caller could not parse the status (a newer
    producer during a rolling deploy) — surfaced as `failed`, the conservative
    outcome. `error` rides along only on `failed`: the record's error text is
    what a client shows after the log expired."""
    status = TERMINAL_STATUS.get(run_status or "", "failed")
    return lifecycle_event(
        [], status, error=(error or None) if status == "failed" else None
    )


# --- messages ----------------------------------------------------------------


def message_start(
    namespace: Namespace,
    node: str | None,
    *,
    role: str,
    message_id: str,
    tool_call_id: str | None = None,
) -> dict:
    data: dict[str, Any] = {"event": "message-start", "role": role, "id": message_id}
    if tool_call_id is not None:
        data["tool_call_id"] = tool_call_id
    return {"method": "messages", "params": _params(namespace, data, node)}


def content_block_start(
    namespace: Namespace, node: str | None, *, index: int, content: dict
) -> dict:
    data = {"event": "content-block-start", "index": index, "content": content}
    return {"method": "messages", "params": _params(namespace, data, node)}


def content_block_delta(
    namespace: Namespace, node: str | None, *, index: int, delta: dict
) -> dict:
    data = {"event": "content-block-delta", "index": index, "delta": delta}
    return {"method": "messages", "params": _params(namespace, data, node)}


def content_block_merge(
    namespace: Namespace, node: str | None, *, index: int, content: dict
) -> dict:
    """`content-block-delta` in its raw-block form: the client merges `content`
    into the block at `index` (string fields concatenate — the shape used for
    `tool_call_chunk` accumulation)."""
    data = {"event": "content-block-delta", "index": index, "content": content}
    return {"method": "messages", "params": _params(namespace, data, node)}


def content_block_finish(
    namespace: Namespace, node: str | None, *, index: int, content: dict
) -> dict:
    data = {"event": "content-block-finish", "index": index, "content": content}
    return {"method": "messages", "params": _params(namespace, data, node)}


def message_finish(
    namespace: Namespace, node: str | None, *, usage: dict | None = None
) -> dict:
    data: dict[str, Any] = {"event": "message-finish"}
    if usage is not None:
        data["usage"] = usage
    return {"method": "messages", "params": _params(namespace, data, node)}


# --- tools -------------------------------------------------------------------


def tool_started(
    namespace: Namespace,
    node: str | None,
    *,
    tool_call_id: str,
    tool_name: str,
    tool_input: Any = None,
) -> dict:
    data: dict[str, Any] = {
        "event": "tool-started",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
    }
    if tool_input is not None:
        data["input"] = tool_input
    return {"method": "tools", "params": _params(namespace, data, node)}


def tool_finished(
    namespace: Namespace, node: str | None, *, tool_call_id: str, output: Any
) -> dict:
    data = {"event": "tool-finished", "tool_call_id": tool_call_id, "output": output}
    return {"method": "tools", "params": _params(namespace, data, node)}


def tool_error(
    namespace: Namespace, node: str | None, *, tool_call_id: str, message: str
) -> dict:
    data = {"event": "tool-error", "tool_call_id": tool_call_id, "message": message}
    return {"method": "tools", "params": _params(namespace, data, node)}


# --- values / input ----------------------------------------------------------


def values_event(namespace: Namespace, data: dict) -> dict:
    return {"method": "values", "params": _params(namespace, data)}


def input_requested(namespace: Namespace, *, interrupt_id: str, payload: Any) -> dict:
    data = {"interrupt_id": interrupt_id, "payload": payload}
    return {"method": "input.requested", "params": _params(namespace, data)}


# --- channel inference / namespace matching (mirrors subscription.js) --------


def infer_channel(event: dict) -> str | None:
    """The subscription channel an event belongs to, or None for unknown
    methods (new server channels must not break old filters)."""
    method = event.get("method")
    if method == "input.requested":
        return "input"
    if method == "custom":
        name = (event.get("params", {}).get("data") or {}).get("name")
        return f"custom:{name}" if name is not None else "custom"
    if method in (
        "values",
        "checkpoints",
        "updates",
        "messages",
        "tools",
        "lifecycle",
        "tasks",
    ):
        return method
    return None


def _normalize_segment(segment: str) -> str:
    """Strip the dynamic suffix (after `:`) from a namespace segment —
    server namespaces look like `tools:<uuid>`, filters say `tools`."""
    idx = segment.find(":")
    return segment if idx == -1 else segment[:idx]


def is_prefix_match(event_namespace: Namespace, prefix: Namespace) -> bool:
    if len(prefix) > len(event_namespace):
        return False
    for filter_segment, candidate in zip(prefix, event_namespace, strict=False):
        if candidate == filter_segment:
            continue
        if ":" in filter_segment:
            return False
        if _normalize_segment(candidate) == filter_segment:
            continue
        return False
    return True


def namespace_matches(
    event_namespace: Namespace,
    prefixes: list[Namespace] | None,
    depth: int | None,
) -> bool:
    if not prefixes:
        # Wildcard namespaces deliver everything — mirrors the client's
        # `namespaceMatches`, which ignores `depth` when no prefixes are given.
        return True
    for prefix in prefixes:
        if not is_prefix_match(event_namespace, prefix):
            continue
        if depth is None or len(event_namespace) - len(prefix) <= depth:
            return True
    return False
