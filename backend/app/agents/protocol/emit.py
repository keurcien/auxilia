"""Worker-side Agent Streaming Protocol emission from LangGraph's native
`astream_events(version="v3")` stream.

`ProtocolEmitter.stream(run)` consumes the raw protocol envelopes an
`AsyncGraphRunStream` yields (`{method, params: {namespace, timestamp, data}}`
for every namespace, subagents included) and yields the wire-ready *event
data* (`{method, params}`) the durable run log stores. The grammar the
client consumes — `message-start` / `content-block-*` / `message-finish`,
`tool-started` / `tool-finished` / `tool-error`, `values`, `lifecycle`,
`input.requested` — is produced by langchain itself; this module only
applies the publish-side policies the web client's contract needs
(reverse-engineered in Part 2, see the package docstring and
`tests/agents/protocol/test_emit.py`):

- Root lifecycle `started` **and** `running` open every run — the client's
  loading tracker flips `isLoading` only on `running`.
- `values` snapshots lose `messages` and `files`: the message projection is
  fed by the `messages` channel, and a message-less snapshot is "refresh the
  non-message blob" (the O(n²) firehose becomes O(n) deltas).
- The input human message never streams on `messages`, so it is echoed
  from the first root `values` snapshot that carries it — once per id,
  string content only — or no live subscriber (a second tab, a reattach,
  the sender's own dropped optimistic copy) ever sees the user's turn.
- Subagent (namespaced) `values` keep exactly one message, the first human
  message, on their first snapshot: the client's `SubagentDiscovery` binds a
  `tools:<task-id>` namespace to its `task` tool call by that text (the task
  id is not the tool-call id; v3's lifecycle `cause` is forwarded too, for
  clients that can use it).
- Tool results ride `tools` **and** `messages`: `tool-finished.output` is
  the ToolMessage content with any MCP artifact wrapped *inside* it as
  `{content, artifact}` (the client's assembler drops extension fields), an
  error ToolMessage becomes `tool-error`, and a closed tool-role message
  triple lets the client's message projection show the tool result. Tool
  calls that never ran (a denied approval, a patched dangling call) have no
  callback; their ToolMessage is read off the node's `updates` delta — the
  exact messages that superstep wrote — so no tool card is left spinning.
  `tool-started` is announced from the model's `updates` delta too (deduped
  with the callback's own), because the client's assembler drops a
  completion for a call it never saw start. `updates` itself is never
  forwarded.
- Interrupts (`params.interrupts` on a `values` envelope) become
  `input.requested`, deduped by interrupt id.
- Namespaced lifecycle payloads (`LifecycleTransformer` forwards them with
  an empty envelope namespace and the real one in `data.namespace`) are
  re-addressed; langgraph's `drained` status maps to `completed`.

The terminal root lifecycle is **not** emitted here: `RunService.finalize`
appends it with the log's `_END` marker once the durable record is
terminal, so the worker, the reaper and an expired-log reattach all
produce exactly one terminal from the same source of truth. A stream error
propagates to the worker (which finalizes the run as `error` with the
root-cause message) instead of being swallowed into an event.
"""

import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from langchain_core.language_models._compat_bridge import message_to_events
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command, Overwrite

from app.agents.protocol import events as ev
from app.agents.protocol.messages import serialize_message, text_of


logger = logging.getLogger(__name__)

#: State keys never forwarded on `values`: messages ride their own channel,
#: interrupts become `input.requested`, and the deepagents virtual filesystem
#: is re-sent on every superstep (megabytes on sandbox-heavy threads) while no
#: stream consumer reads it — history comes from the checkpoint.
_VALUES_DROP = frozenset({"messages", "files", "__interrupt__"})

#: langgraph `SubgraphStatus` → protocol `AgentStatus`.
_SUBGRAPH_STATUS = {
    "started": "started",
    "completed": "completed",
    "failed": "failed",
    "interrupted": "interrupted",
    "drained": "completed",
}


#: `str(GraphInterrupt(...))` — the shape a bubbling interrupt takes on the
#: `tools` channel's `tool-error` message.
_INTERRUPT_REPR = re.compile(r"^\(?Interrupt\(")
#: The ``id='<xxh3-128 hex>'`` field(s) inside that repr.
_INTERRUPT_ID_IN_REPR = re.compile(r"\bid='([0-9a-f]{32})'")


def _ns_key(namespace: list[str]) -> str:
    return "|".join(namespace)


def _unwrap(value: Any) -> Any:
    return value.value if isinstance(value, Overwrite) else value


class ProtocolEmitter:
    """Stateful, single-run translation of v3 envelopes into wire events.

    Feed one run's `AsyncGraphRunStream` to :meth:`stream`. Dedup state
    (interrupt ids, echoed message ids, bound namespaces) lives for the run.
    """

    def __init__(self) -> None:
        self._interrupt_ids: set[str] = set()
        self._echoed_message_ids: set[str] = set()
        self._bound_namespaces: set[str] = set()
        self._tool_started_ids: set[str] = set()
        #: tool-call id -> tool name, from `tool-started`; a bubbling
        #: interrupt is only ever reported against the `task` tool.
        self._tool_names: dict[str, str] = {}
        self._tool_finished_ids: set[str] = set()

    async def stream(self, run: AsyncIterator[dict]) -> AsyncGenerator[dict, None]:
        """Yield wire events for one run, opening with the root lifecycle.

        Exceptions the graph raises surface here after the buffered events
        (the run stream fails its log) and propagate to the caller."""
        yield ev.lifecycle_event([], "started")
        yield ev.lifecycle_event([], "running")
        async for envelope in run:
            for event in self.translate(envelope):
                yield event

    # --- envelope dispatch -----------------------------------------------------

    def translate(self, envelope: dict) -> list[dict]:
        """Wire events for one raw v3 envelope (pure; testable without a graph)."""
        method = envelope.get("method")
        params = envelope.get("params") or {}
        namespace = list(params.get("namespace") or [])
        data = params.get("data")
        if method == "messages":
            return self._on_messages(namespace, data)
        if method == "values":
            return self._on_values(namespace, data, params.get("interrupts"))
        if method == "tools":
            return self._on_tools(namespace, data)
        if method == "lifecycle":
            return self._on_lifecycle(data)
        if method == "updates":
            return self._on_updates(namespace, data)
        if method == "custom":
            return [{"method": "custom", "params": ev._params(namespace, data)}]
        # `checkpoints`, `tasks`, `debug`: not requested, or folded into the
        # projections above by langgraph.
        return []

    # --- messages ----------------------------------------------------------------

    def _on_messages(self, namespace: list[str], data: Any) -> list[dict]:
        if not isinstance(data, (list, tuple)) or len(data) != 2:
            return []
        payload, metadata = data
        node = (
            (metadata or {}).get("langgraph_node")
            if isinstance(metadata, dict)
            else None
        )
        if isinstance(payload, dict) and "event" in payload:
            # Already protocol grammar (v2 chat-model streaming): forward as-is.
            return [
                {"method": "messages", "params": ev._params(namespace, payload, node)}
            ]
        if isinstance(payload, ToolMessage):
            # Tool results are surfaced from the `tools` channel (they carry
            # the artifact and the error status there); v2 streaming doesn't
            # replay them on `messages` anyway.
            return []
        if isinstance(payload, AIMessage) and not isinstance(payload, AIMessageChunk):
            # A node returned a finalized AIMessage (middleware fallbacks such
            # as ModelRetryMiddleware's failure notice, the recursion-limit
            # notice): replay it as the same event lifecycle a live call
            # would produce.
            return [
                {"method": "messages", "params": ev._params(namespace, e, node)}
                for e in message_to_events(payload, message_id=payload.id)
            ]
        if isinstance(payload, BaseMessage) and payload.type in ("human", "system"):
            return self._whole_message(namespace, node, payload, role=payload.type)
        return []

    def _whole_message(
        self,
        namespace: list[str],
        node: str | None,
        message: BaseMessage,
        *,
        role: str,
    ) -> list[dict]:
        """A complete non-AI message as a closed start/block/finish triple,
        emitted once per (namespace, role, id)."""
        message_id = message.id
        if not isinstance(message_id, str) or not message_id:
            return []
        key = f"{_ns_key(namespace)}|{role}|{message_id}"
        if key in self._echoed_message_ids:
            return []
        self._echoed_message_ids.add(key)
        return [
            ev.message_start(namespace, node, role=role, message_id=message_id),
            ev.content_block_start(
                namespace,
                node,
                index=0,
                content={"type": "text", "text": text_of(message.content)},
            ),
            ev.message_finish(namespace, node),
        ]

    # --- values -----------------------------------------------------------------

    def _on_values(
        self, namespace: list[str], data: Any, interrupts: Any
    ) -> list[dict]:
        if not isinstance(data, dict):
            return []
        out: list[dict] = []
        trimmed = {k: _unwrap(v) for k, v in data.items() if k not in _VALUES_DROP}
        messages = _unwrap(data.get("messages")) or []
        if namespace:
            key = _ns_key(namespace)
            if key not in self._bound_namespaces:
                self._bound_namespaces.add(key)
                first_human = next(
                    (m for m in messages if isinstance(m, HumanMessage)), None
                )
                if first_human is not None:
                    trimmed["messages"] = [serialize_message(first_human)]
            out.append(ev.values_event(namespace, trimmed))
            out.extend(self._input_requested(namespace, interrupts))
            return out

        out.append(ev.values_event([], trimmed))
        for message in messages:
            # Block-content human messages (attachments) are skipped: the
            # client's assembler flattens human echoes to text, and replacing
            # a richer optimistic copy with that would lose the attachments.
            # A real id is required — every superstep repeats the message and
            # only an id makes the echo deduplicable.
            if isinstance(message, HumanMessage) and isinstance(message.content, str):
                out.extend(self._whole_message([], None, message, role="human"))
        out.extend(self._input_requested([], interrupts))
        return out

    def _input_requested(self, namespace: list[str], interrupts: Any) -> list[dict]:
        """`input.requested` for each interrupt not yet announced.

        A subagent's interrupt rides on two `values` envelopes: its own
        namespace's first (langgraph streams the subgraph's superstep before
        the parent's), then the root's, once it has bubbled up through the
        `task` tool. The first one wins, so the event carries the namespace
        of the agent that actually paused and the client can pin the approval
        to that subagent's card; the root copy is dropped by id.
        """
        out: list[dict] = []
        for interrupt in interrupts or ():
            interrupt_id = getattr(interrupt, "id", None)
            value = getattr(interrupt, "value", interrupt)
            if isinstance(interrupt, dict):
                interrupt_id, value = interrupt.get("id"), interrupt.get("value")
            if not isinstance(interrupt_id, str) or interrupt_id in self._interrupt_ids:
                continue
            self._interrupt_ids.add(interrupt_id)
            out.append(
                ev.input_requested(namespace, interrupt_id=interrupt_id, payload=value)
            )
        return out

    # --- updates ------------------------------------------------------------------

    def _on_updates(self, namespace: list[str], data: Any) -> list[dict]:
        """Complete tool calls that never ran through a tool.

        The `tools` channel is fed by tool callbacks, so a ToolMessage a node
        writes straight into state has no `tool-finished`/`tool-error` of its
        own: the rejection notice `HumanInTheLoopMiddleware` synthesizes for a
        denied call, the answers `PatchToolCallsMiddleware` fabricates for
        calls left dangling by an aborted turn, the error messages the repair
        middleware feeds back for malformed calls. Without a completion the
        client's tool card spins for ever. An `updates` delta is exactly what
        one node wrote in one superstep, so every ToolMessage in it whose
        call has not completed on the channel is completed from here —
        deduped by tool-call id with the channel, so a tool that did run is
        not reported twice. The delta itself is not forwarded."""
        if not isinstance(data, dict):
            return []
        out: list[dict] = []
        for node_update in data.values():
            if not isinstance(node_update, dict):
                continue
            messages = _unwrap(node_update.get("messages"))
            if isinstance(messages, BaseMessage):
                messages = [messages]
            for message in messages or []:
                if isinstance(message, AIMessage) and not isinstance(
                    message, AIMessageChunk
                ):
                    # Announce every call the model made, as the legacy log
                    # did. The client's assembler only tracks calls it saw
                    # start, so a completion for a call that never ran (below)
                    # would otherwise be dropped on the floor. The tool
                    # callback's own `tool-started` is deduped against this.
                    for tc in message.tool_calls or []:
                        out.extend(
                            self._tool_started(
                                namespace,
                                tool_call_id=tc.get("id"),
                                tool_name=tc.get("name"),
                                tool_input=tc.get("args"),
                            )
                        )
                elif isinstance(message, ToolMessage) and message.tool_call_id:
                    if message.tool_call_id in self._tool_finished_ids:
                        continue
                    # A patched dangling call answers an AI message from an
                    # earlier turn, so its start may not be in this delta.
                    out.extend(
                        self._tool_started(
                            namespace,
                            tool_call_id=message.tool_call_id,
                            tool_name=message.name,
                        )
                    )
                    self._tool_finished_ids.add(message.tool_call_id)
                    out.extend(
                        self._tool_result(namespace, message.tool_call_id, message)
                    )
        return out

    def _tool_started(
        self,
        namespace: list[str],
        *,
        tool_call_id: Any,
        tool_name: Any,
        tool_input: Any = None,
    ) -> list[dict]:
        """`tool-started` once per tool-call id, whichever source sees it first."""
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return []
        if tool_call_id in self._tool_started_ids:
            return []
        if isinstance(tool_name, str):
            self._tool_names[tool_call_id] = tool_name
        self._tool_started_ids.add(tool_call_id)
        return [
            ev.tool_started(
                namespace,
                None,
                tool_call_id=tool_call_id,
                tool_name=str(tool_name or "tool"),
                tool_input=tool_input,
            )
        ]

    # --- tools ------------------------------------------------------------------

    def _on_tools(self, namespace: list[str], data: Any) -> list[dict]:
        if not isinstance(data, dict):
            return []
        kind = data.get("event")
        tool_call_id = data.get("tool_call_id")
        if kind == "tool-started":
            return self._tool_started(
                namespace,
                tool_call_id=tool_call_id,
                tool_name=data.get("tool_name"),
                tool_input=data.get("input"),
            )
        if kind == "tool-error":
            if not tool_call_id or tool_call_id in self._tool_finished_ids:
                return []
            if self._is_bubbling_interrupt(str(tool_call_id), data.get("message")):
                # A subagent's approval interrupt bubbles up through the
                # `task` tool, and langgraph reports that to the parent's
                # tool callbacks as a failure. It is not one: the call is
                # paused, its subagent resumes into the same call later, and
                # forwarding this would have the client mark the subagent
                # card errored (with the Interrupt repr as the message) for
                # the length of the pause. Leave the call running.
                return []
            self._tool_finished_ids.add(tool_call_id)
            return [
                ev.tool_error(
                    namespace,
                    None,
                    tool_call_id=str(tool_call_id),
                    message=str(data.get("message") or "Tool failed"),
                )
            ]
        if kind == "tool-finished":
            if not tool_call_id or tool_call_id in self._tool_finished_ids:
                return []
            self._tool_finished_ids.add(tool_call_id)
            return self._tool_result(namespace, str(tool_call_id), data.get("output"))
        # `tool-output-delta` is not part of the client contract yet.
        return []

    def _is_bubbling_interrupt(self, tool_call_id: str, message: Any) -> bool:
        """Whether a `task` call's `tool-error` is a `GraphInterrupt` in flight.

        langgraph stringifies the exception: ``(Interrupt(value=..., id='…'),)``.
        Three checks, so a genuine failure is never mistaken for a pause: the
        failing call is the `task` tool (name recorded at `tool-started`), the
        message has the repr's shape, and it names at least one interrupt id,
        every one of which the subagent's own `values` envelope announced
        just before.
        """
        if self._tool_names.get(tool_call_id) != "task":
            return False
        if not isinstance(message, str) or _INTERRUPT_REPR.match(message) is None:
            return False
        named = _INTERRUPT_ID_IN_REPR.findall(message)
        if not named:
            # langgraph's repr always names the id; a shape without one is
            # some other failure and must reach the client.
            return False
        return all(interrupt_id in self._interrupt_ids for interrupt_id in named)

    def _tool_result(
        self, namespace: list[str], tool_call_id: str, output: Any
    ) -> list[dict]:
        message = _tool_message_of(output, tool_call_id)
        if message is None:
            return [
                ev.tool_finished(
                    namespace, None, tool_call_id=tool_call_id, output=output
                )
            ]
        content: Any = message.content
        text = text_of(content)
        message_id = message.id or f"tool-{tool_call_id}"
        out = [
            ev.message_start(
                namespace,
                None,
                role="tool",
                message_id=message_id,
                tool_call_id=tool_call_id,
            ),
            ev.content_block_start(
                namespace, None, index=0, content={"type": "text", "text": text}
            ),
            ev.message_finish(namespace, None),
        ]
        if message.status == "error":
            out.append(
                ev.tool_error(namespace, None, tool_call_id=tool_call_id, message=text)
            )
            return out
        # MCP tool artifacts (structured content, app resource URIs) must ride
        # INSIDE `output`: the client's ToolCallAssembler keeps only
        # output/status/error, dropping extension fields, and its
        # `parseToolOutput` passes plain objects through untouched. The web
        # adapter unwraps `{content, artifact}` back apart.
        if message.artifact is not None:
            content = {"content": content, "artifact": message.artifact}
        out.append(
            ev.tool_finished(namespace, None, tool_call_id=tool_call_id, output=content)
        )
        return out

    # --- lifecycle --------------------------------------------------------------

    def _on_lifecycle(self, data: Any) -> list[dict]:
        if not isinstance(data, dict):
            return []
        namespace = list(data.get("namespace") or [])
        if not namespace:
            # Root lifecycle is owned by this emitter (`started`/`running`)
            # and by `finalize` (the terminal); langgraph emits none today.
            return []
        status = _SUBGRAPH_STATUS.get(str(data.get("event")))
        if status is None:
            return []
        return [
            ev.lifecycle_event(
                namespace,
                status,
                error=data.get("error"),
                graph_name=data.get("graph_name"),
                cause=data.get("cause"),
            )
        ]

    # --- out-of-band messages -----------------------------------------------------

    @staticmethod
    def synthetic_ai_message(
        message: AIMessage, state_values: dict[str, Any]
    ) -> list[dict]:
        """Wire events for an AI message the runtime persisted after the graph
        stopped (the recursion-limit fallback): the message lifecycle plus a
        trimmed root `values` refresh, so the client renders it without a
        special-case path."""
        out = [
            {"method": "messages", "params": ev._params([], e, None)}
            for e in message_to_events(message, message_id=message.id)
        ]
        trimmed = {
            k: _unwrap(v) for k, v in state_values.items() if k not in _VALUES_DROP
        }
        out.append(ev.values_event([], trimmed))
        return out


def _tool_message_of(output: Any, tool_call_id: str) -> ToolMessage | None:
    """The ToolMessage behind a `tool-finished` output, if there is one.

    `StreamToolCallHandler.on_tool_end` receives the tool's formatted output:
    a `ToolMessage` for ordinary tools, or a `Command` whose state update
    carries the ToolMessage for tools that write state (the deepagents
    `task` tool)."""
    if isinstance(output, ToolMessage):
        return output
    if isinstance(output, Command):
        update = output.update
        messages = update.get("messages") if isinstance(update, dict) else None
        for m in _unwrap(messages) or []:
            if isinstance(m, ToolMessage) and m.tool_call_id == tool_call_id:
                return m
        for m in _unwrap(messages) or []:
            if isinstance(m, ToolMessage):
                return m
    return None
