"""HITL interrupt state — reading it off a checkpoint, answering it.

The LangGraph checkpoint is the source of truth for "this thread is waiting
on approvals": a graph paused on `HumanInTheLoopMiddleware` leaves an
`__interrupt__` entry in the checkpoint's `pending_writes` carrying a stable
interrupt id (a hash of the interrupting task's namespace — recomputed from
the checkpoint on every read, stored nowhere by us). Everything here is a
pure function of a checkpoint tuple plus client-supplied decisions: no
session, no Redis, nothing that can expire.

A subagent's gated tool interrupts too (deepagents' `task` runs it as a
nested subgraph on the same checkpointer): the interrupt propagates to the
root checkpoint's `pending_writes` under the parent's `tools` task, while the
gated tool call itself lives in the subagent's own checkpoint, namespaced
`tools:<that task id>`. `load_interrupt_scope` follows that link so approvals
carry the real `tool_call_id` whichever agent paused; the pure helpers take
the interrupting (root) checkpoint plus that `scope` checkpoint.

Consumers: the thread read endpoint (rehydrating the approval UI), the run
worker (terminal-status detection), the Slack consumer (posting approval
cards), `RunService.create` (canonicalizing an addressed resume), and the
protocol state snapshot (interrupt namespace for the client).
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
    #: The pending write's task id — for an interrupt that bubbled up from a
    #: subagent, the parent's `tools` task, i.e. the subagent's namespace is
    #: ``tools:<task_id>``. None for the dict shapes that don't carry one.
    task_id: str | None = None


class InterruptScope(NamedTuple):
    """A pending interrupt located to the checkpoint that holds its tool calls.

    `root` is the thread's root checkpoint tuple (the interrupt, its id and the
    resume target live there); `checkpoint` is the tuple whose `messages`
    channel holds the gated tool calls — the root itself for a parent-agent
    approval, the subagent's `tools:<task-id>` checkpoint (nested further as
    `tools:<a>|tools:<b>` for a subagent's subagent) when a subagent paused.
    `namespace` is that checkpoint namespace (``""`` at the root) and
    `subagent_call` the root `task` tool call awaiting the paused subagent.
    """

    root: Any
    interrupt: PendingInterrupt
    namespace: str
    checkpoint: Any
    subagent_call: dict[str, Any] | None

    @property
    def namespace_path(self) -> list[str]:
        """The namespace as the protocol's segment list (``[]`` at the root)."""
        return [seg for seg in self.namespace.split(_NS_SEP) if seg]

    @property
    def subagent_type(self) -> str | None:
        """The paused subagent's `subagent_type`, when a subagent paused."""
        if self.subagent_call is None:
            return None
        return (self.subagent_call.get("args") or {}).get("subagent_type")


#: How many `task` levels `load_interrupt_scope` follows — a subagent's
#: subagent's subagent is already deeper than any agent graph auxilia builds.
MAX_SUBAGENT_DEPTH = 4

#: langgraph's checkpoint-namespace separator (`langgraph.constants.NS_SEP`).
_NS_SEP = "|"
_TOOLS_NS_PREFIX = "tools:"


#: `Command(resume=...)` is treated as a map keyed by interrupt ids only when
#: every key is an xxh3-128 hexdigest (langgraph's `is_xxh3_128_hexdigest`).
#: Anything else — e.g. langgraph's "placeholder-id" default — must use the
#: plain resume form or the middleware would receive the map as its payload.
_INTERRUPT_ID_RE = re.compile(r"[0-9a-f]{32}")


def pending_interrupts(checkpoint_tuple: Any) -> list[PendingInterrupt]:
    """Every pending HITL interrupt on a checkpoint tuple, in write order.

    One per paused task: a parent approval or a paused subagent is one entry;
    several subagents pausing in the same superstep are several. Tolerates
    both an `Interrupt` object (the serde round-trips it) and a plain
    ``{"value": ..., "id": ...}`` dict, mirroring the two shapes the live
    stream and older checkpoints produce.
    """
    found: list[PendingInterrupt] = []
    for task_id, channel, value in (
        getattr(checkpoint_tuple, "pending_writes", None) or []
    ):
        if channel != "__interrupt__":
            continue
        batch = value if isinstance(value, (list, tuple)) else [value]
        if not batch:
            continue
        first = batch[0]
        if isinstance(first, dict) and "value" in first:
            found.append(
                PendingInterrupt(
                    id=first.get("id"), value=first.get("value"), task_id=task_id
                )
            )
        else:
            found.append(
                PendingInterrupt(
                    id=getattr(first, "id", None),
                    value=getattr(first, "value", first),
                    task_id=task_id,
                )
            )
    return found


def pending_interrupt(
    checkpoint_tuple: Any, interrupt_id: str | None = None
) -> PendingInterrupt | None:
    """The pending interrupt with `interrupt_id`, or the first one, or None.

    An addressed resume names its interrupt, which matters once parallel
    subagents can pause together; every other reader (terminal-status
    detection, Slack cards) deals with "the" pending interrupt.
    """
    interrupts = pending_interrupts(checkpoint_tuple)
    if interrupt_id is not None:
        return next((i for i in interrupts if i.id == interrupt_id), None)
    return interrupts[0] if interrupts else None


async def load_interrupt_scope(
    checkpointer: Any,
    thread_id: str,
    root: Any = None,
    interrupt_id: str | None = None,
) -> InterruptScope | None:
    """Locate the thread's pending interrupt, or None when nothing is pending.

    Reads the root checkpoint (or takes it as `root`) and picks the interrupt
    (`interrupt_id` when an addressed resume names one, else the first); see
    `_scope_of` for the descent into the paused subagent.
    """
    if root is None:
        root = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id}}
        )
    interrupt = pending_interrupt(root, interrupt_id)
    if interrupt is None:
        return None
    return await _scope_of(checkpointer, thread_id, root, interrupt)


async def load_interrupt_scopes(
    checkpointer: Any, thread_id: str, root: Any = None
) -> list[InterruptScope]:
    """Every pending interrupt on the thread, each located to its scope — by
    its own pending write, so id-less (older) entries resolve too."""
    if root is None:
        root = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id}}
        )
    return [
        await _scope_of(checkpointer, thread_id, root, interrupt)
        for interrupt in pending_interrupts(root)
    ]


async def _scope_of(
    checkpointer: Any, thread_id: str, root: Any, interrupt: PendingInterrupt
) -> InterruptScope:
    """Follow `interrupt`'s task into `tools:<task_id>` for as long as a
    checkpoint exists there and is paused on the *same* interrupt id: one hop
    for a subagent, one more per nesting level, none for a parent-agent
    approval (its pending write's task is the HITL node, which has no
    namespace of its own). The descent is bounded by `MAX_SUBAGENT_DEPTH` so
    a checkpointer answering every namespace can never make it loop. The root
    `task` call that started the paused subagent is matched on the first hop,
    where the child's seed message is that call's description."""
    namespace, scope, current = "", root, interrupt
    subagent_call: dict[str, Any] | None = None
    for _ in range(MAX_SUBAGENT_DEPTH):
        if not current.task_id:
            break
        child_ns = f"{namespace}{_NS_SEP if namespace else ''}{_TOOLS_NS_PREFIX}{current.task_id}"
        child = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": child_ns}}
        )
        child_interrupt = (
            pending_interrupt(child, interrupt.id) if child is not None else None
        )
        if child_interrupt is None:
            break
        if not namespace:
            subagent_call = _paused_task_call(root, _messages_of(child))
        namespace, scope, current = child_ns, child, child_interrupt
    return InterruptScope(
        root=root,
        interrupt=interrupt,
        namespace=namespace,
        checkpoint=scope,
        subagent_call=subagent_call,
    )


def pending_approval_requests(
    checkpoint_tuple: Any, scope: Any = None
) -> list[dict[str, Any]]:
    """Return the tool calls awaiting human approval on a paused checkpoint.

    `HumanInTheLoopMiddleware` interrupts with a `HITLRequest` whose
    `action_requests` carry only `name`/`args` (no id), and resume `decisions`
    are positional. We re-attach each request to the originating tool call (by
    name+args, falling back to position) so callers get a stable
    `tool_call_id` for the approve/reject UI. Returns `[]` when not interrupted.

    The interrupt is read off `checkpoint_tuple` (the root); the tool calls off
    `scope` when given — the subagent checkpoint `load_interrupt_scope`
    located — else off the same tuple. Without the scope, a subagent's
    approvals fall back to positional `approval-<i>` ids: the root's last AI
    message only carries the `task` call.
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

    tool_calls = _last_pending_tool_calls(
        _messages_of(scope if scope is not None else checkpoint_tuple)
    )

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
    checkpoint_tuple: Any, resume: dict[str, Any], scope: Any = None
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

    `scope` is the checkpoint holding the gated tool calls (see
    `pending_approval_requests`); the resume itself always targets the root.

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

    expected = [
        r["tool_call_id"] for r in pending_approval_requests(checkpoint_tuple, scope)
    ]
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


def _messages_of(checkpoint_tuple: Any) -> list:
    return (
        (getattr(checkpoint_tuple, "checkpoint", None) or {})
        .get("channel_values", {})
        .get("messages", [])
    )


def _paused_task_call(root: Any, scope_messages: list) -> dict[str, Any] | None:
    """The root `task` tool call whose subagent is the paused one.

    Several subagents can run in parallel, so the pending `task` calls are
    told apart by the subagent's seed: `task` starts the subagent with its
    `description` as the first human message.
    """
    pending = [
        tc
        for tc in _last_pending_tool_calls(_messages_of(root))
        if tc.get("name") == "task"
    ]
    if not pending:
        return None
    seed = scope_messages[0].content if scope_messages else None
    for tc in pending:
        if (tc.get("args") or {}).get("description") == seed:
            return tc
    return pending[0] if len(pending) == 1 else None


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
