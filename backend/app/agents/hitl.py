"""HITL interrupt state — reading it off a checkpoint, answering it.

The LangGraph checkpoint is the source of truth for "this thread is waiting
on approvals": a graph paused on `HumanInTheLoopMiddleware` leaves an
`__interrupt__` entry in the checkpoint's `pending_writes` carrying a stable
interrupt id (a hash of the interrupting task's namespace — recomputed from
the checkpoint on every read, stored nowhere by us). Everything here is a
pure function of a checkpoint tuple plus client-supplied decisions: no
session, no Redis, nothing that can expire.

Consumers: the thread read endpoint (rehydrating the approval UI), the run
worker (terminal-status detection), the Slack consumer (posting approval
cards), and `RunService.create` (canonicalizing an addressed resume).
"""

import re
from typing import Any, NamedTuple

from langchain_core.messages import ToolMessage

from app.exceptions import DomainValidationError, StaleApprovalError


class PendingInterrupt(NamedTuple):
    """The interrupt a paused thread is waiting on.

    `id` is None when the checkpoint's serde didn't round-trip the
    `Interrupt` object (older rows) — callers must tolerate it: display
    paths omit it, and `build_resume_command` falls back to the plain
    (unaddressed) resume form.
    """

    id: str | None
    value: Any


#: `Command(resume=...)` is treated as a map keyed by interrupt ids only when
#: every key is an xxh3-128 hexdigest (langgraph's `is_xxh3_128_hexdigest`).
#: Anything else — e.g. langgraph's "placeholder-id" default — must use the
#: plain resume form or the middleware would receive the map as its payload.
_INTERRUPT_ID_RE = re.compile(r"[0-9a-f]{32}")


def pending_interrupt(checkpoint_tuple: Any) -> PendingInterrupt | None:
    """Return the pending HITL interrupt from a checkpoint tuple, or None.

    Tolerates both an `Interrupt` object (the serde round-trips it) and a
    plain ``{"value": ..., "id": ...}`` dict, mirroring the two shapes the
    live stream and older checkpoints produce.
    """
    for _, channel, value in getattr(checkpoint_tuple, "pending_writes", None) or []:
        if channel != "__interrupt__":
            continue
        batch = value if isinstance(value, (list, tuple)) else [value]
        if not batch:
            continue
        first = batch[0]
        if isinstance(first, dict) and "value" in first:
            return PendingInterrupt(id=first.get("id"), value=first.get("value"))
        return PendingInterrupt(
            id=getattr(first, "id", None), value=getattr(first, "value", first)
        )
    return None


def pending_approval_requests(checkpoint_tuple: Any) -> list[dict[str, Any]]:
    """Return the tool calls awaiting human approval on a paused checkpoint.

    `HumanInTheLoopMiddleware` interrupts with a `HITLRequest` whose
    `action_requests` carry only `name`/`args` (no id), and resume `decisions`
    are positional. We re-attach each request to the originating tool call (by
    name+args, falling back to position) so callers get a stable
    `tool_call_id` for the approve/reject UI. Returns `[]` when not interrupted.
    """
    interrupt = pending_interrupt(checkpoint_tuple)
    interrupt_value = interrupt.value if interrupt else None
    requests = (
        (interrupt_value or {}).get("action_requests")
        if (isinstance(interrupt_value, dict))
        else None
    )
    if not requests:
        return []

    channel_values = getattr(checkpoint_tuple, "checkpoint", {}).get(
        "channel_values", {}
    )
    tool_calls = _last_pending_tool_calls(channel_values.get("messages", []))

    approvals: list[dict[str, Any]] = []
    used: set[int] = set()
    for index, request in enumerate(requests):
        match = _match_tool_call(request, tool_calls, used)
        approvals.append(
            {
                "tool_call_id": (match or {}).get("id") or f"approval-{index}",
                "tool_name": request.get("name", "unknown"),
                "input": request.get("args", {}),
            }
        )
    return approvals


def is_addressed_resume(resume: Any) -> bool:
    """Whether a client resume payload names the interrupt it answers.

    Addressed: ``{"interrupt_id": ..., "decisions": [{"tool_call_id": ...,
    "type": ...}, ...]}``. Anything else is passed through untouched — the
    legacy positional ``{"decisions": [...]}``, a replayed canonical command,
    or a free-form resume value.
    """
    return isinstance(resume, dict) and "interrupt_id" in resume


def build_resume_command(
    checkpoint_tuple: Any, resume: dict[str, Any]
) -> dict[str, Any]:
    """Turn an addressed resume into the canonical command to store and run.

    The client's decisions are keyed by ``tool_call_id`` and order-free; the
    middleware's `HITLResponse.decisions` is positional. The order comes from
    the checkpoint here — never from the client — so no UI reordering of the
    approval cards can misassign a decision.

    Output: ``{"resume": {<interrupt_id>: {"decisions": [...]}}}`` — the
    id-keyed form, so LangGraph applies it only to the addressed interrupt.
    When the checkpoint carries no usable id, falls back to the plain form,
    which still targets the single pending interrupt.

    Raises `StaleApprovalError` when nothing is pending or the addressed
    interrupt was already resolved (the thread moved on — e.g. approved from
    another surface), and `DomainValidationError` when the decisions don't
    cover the pending requests exactly.
    """
    pending = pending_interrupt(checkpoint_tuple)
    if pending is None:
        raise StaleApprovalError("No approval is pending on this thread.")
    if pending.id is not None and resume.get("interrupt_id") != pending.id:
        raise StaleApprovalError("This approval request was already handled.")

    # No `or []`: a falsy non-list ({}, 0, "", explicit null) must reach the
    # type check and fail loudly, not coerce into "no decisions supplied".
    decisions = resume.get("decisions", [])
    if not isinstance(decisions, list):
        raise DomainValidationError("`decisions` must be a list.")
    supplied: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict) or not isinstance(
            decision.get("tool_call_id"), str
        ):
            raise DomainValidationError("Each decision needs a string tool_call_id.")
        supplied[decision["tool_call_id"]] = {
            k: v for k, v in decision.items() if k != "tool_call_id"
        }

    expected = [r["tool_call_id"] for r in pending_approval_requests(checkpoint_tuple)]
    missing = [tc for tc in expected if tc not in supplied]
    unknown = [tc for tc in supplied if tc not in expected]
    if missing or unknown:
        raise DomainValidationError(
            "Decisions do not match the pending approvals "
            f"(missing: {missing}, unknown: {unknown})."
        )

    payload = {"decisions": [supplied[tc] for tc in expected]}
    if pending.id is None or not _INTERRUPT_ID_RE.fullmatch(pending.id):
        return {"resume": payload}
    return {"resume": {pending.id: payload}}


def _last_pending_tool_calls(messages: list) -> list[dict[str, Any]]:
    """Tool calls on the last AI message that have no result yet."""
    resulted = {
        getattr(m, "tool_call_id", None) for m in messages if isinstance(m, ToolMessage)
    }
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            return [tc for tc in tool_calls if tc.get("id") not in resulted]
    return []


def _match_tool_call(
    request: dict, tool_calls: list[dict], used: set[int]
) -> dict | None:
    """Find the unused tool call for an action request.

    Prefers an exact name+args match; falls back to the first unused call with
    the same name (covers two calls to the same tool with identical args).
    """
    candidates = [
        (i, tc)
        for i, tc in enumerate(tool_calls)
        if i not in used and tc.get("name") == request.get("name")
    ]
    if not candidates:
        return None
    for i, tc in candidates:
        if tc.get("args") == request.get("args"):
            used.add(i)
            return tc
    i, tc = candidates[0]
    used.add(i)
    return tc
