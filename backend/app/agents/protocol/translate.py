"""Legacy LangGraph SSE → Agent Streaming Protocol events.

The durable runtime's event log stays in the canonical legacy format the
worker already publishes (`event: messages|values|updates|error|end`); this
translator turns that log into the delta-based protocol the `@langchain/react`
client consumes. It is deliberately **deterministic**: a given log prefix
always yields the same protocol event sequence, so a stream session that
replays from the start (the client's rotation strategy) reproduces identical
`event_id`s and the client's dedup does the rest.

What the translation buys on the wire (issue #309):

- `values` snapshots lose their `messages` array — the client's message
  projection is maintained from the `messages` delta channel, and its
  `applyValues` treats a message-less snapshot as "refresh the non-message
  blob" (verified against `root-message-projection.js`). The O(n²) full-state
  firehose becomes O(n) deltas.
- `updates` events are not forwarded at all; they only feed the `tools`
  channel derivation here.
- Subagent (namespaced) `values` keep exactly one message — the first human
  message — because the client's `SubagentDiscovery` binds a `tools:<task-id>`
  namespace to its `task` tool call by that text (the task id is not the
  tool-call id).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.protocol import events as ev
from app.agents.runs.state import RunStatus


logger = logging.getLogger(__name__)

_AI_TYPES = ("AIMessageChunk", "ai", "AIMessage")

#: RunStatus → protocol AgentStatus for the terminal root lifecycle event.
#: `cancelled` maps to completed: a user Stop is not a failure, and the
#: protocol has no cancelled status.
_TERMINAL_STATUS = {
    RunStatus.success: "completed",
    RunStatus.interrupted: "interrupted",
    RunStatus.error: "failed",
    RunStatus.timeout: "failed",
    RunStatus.cancelled: "completed",
}


def _ns_key(namespace: list[str]) -> str:
    return "|".join(namespace)


def _text_of(content: Any) -> str:
    """Stringify a message `content` for a text block."""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


@dataclass
class _OpenMessage:
    """Assembly state for one in-flight message on a (namespace, node)."""

    id: str | None
    role: str
    # block key ("text", "reasoning", "tc:<chunk index>") → protocol block index
    blocks: dict[str, int] = field(default_factory=dict)
    next_index: int = 0
    # tool-call chunk accumulation: block key → {"id", "name", "args"}
    tool_call_chunks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # complete tool calls seen on chunks (providers that send them whole)
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None


class ProtocolTranslator:
    """Stateful translator for one run's legacy SSE event sequence.

    Feed decoded legacy `(event_name, data)` pairs to :meth:`translate` in log
    order; call :meth:`finish` after the terminal sentinel. Each call returns
    the protocol events (plain ``{method, params}`` dicts) that leg of the log
    produces, in order.
    """

    def __init__(self) -> None:
        # (ns_key, node) → open message state
        self._open: dict[tuple[str, str], _OpenMessage] = {}
        self._started = False
        self._seen_namespaces: set[str] = set()
        self._tool_started_ids: set[str] = set()
        self._tool_finished_ids: set[str] = set()
        self._interrupt_ids: set[str] = set()
        self._terminal_emitted = False

    # --- entry points --------------------------------------------------------

    def translate(self, event_name: str, data: Any) -> list[dict]:
        mode, _, ns_str = event_name.partition("|")
        namespace = ns_str.split("|") if ns_str else []
        out: list[dict] = []
        if not self._started:
            self._started = True
            out.append(ev.lifecycle_event([], "started"))
        if namespace and _ns_key(namespace) not in self._seen_namespaces:
            self._seen_namespaces.add(_ns_key(namespace))
            out.append(ev.lifecycle_event(namespace, "started"))

        if mode == "messages":
            out.extend(self._on_messages(namespace, data))
        elif mode == "values":
            out.extend(self._on_values(namespace, data))
        elif mode == "updates":
            out.extend(self._on_updates(namespace, data))
        elif mode == "error":
            # The error event is the terminal that carries the message; mark
            # it emitted so `finish` (driven by the worker's end sentinel,
            # which follows the error) doesn't add a second terminal.
            message = data.get("message") if isinstance(data, dict) else str(data)
            out.extend(self._finish_all_open())
            self._terminal_emitted = True
            out.append(
                ev.lifecycle_event([], "failed", error=message or "Unknown error")
            )
        # `end` sentinels are handled by `finish` (the service knows the
        # terminal status even when the log expired); other modes are ignored.
        return out

    def finish(self, status: RunStatus | None) -> list[dict]:
        """Close every open message and emit the terminal root lifecycle —
        unless an `error` event already emitted it with the failure message.

        `status=None` means the sentinel carried a status this build doesn't
        know (a newer producer mid-deploy): surface it as `failed` — the
        conservative outcome, matching the Slack consumer's generic failure
        notice — never as a false `completed`."""
        out = self._finish_all_open()
        if not self._terminal_emitted:
            self._terminal_emitted = True
            terminal = _TERMINAL_STATUS.get(status) if status is not None else None
            out.append(ev.lifecycle_event([], terminal or "failed"))
        return out

    # --- messages mode ---------------------------------------------------------

    def _on_messages(self, namespace: list[str], data: Any) -> list[dict]:
        if not isinstance(data, list) or not data:
            return []
        chunk = data[0]
        if not isinstance(chunk, dict):
            return []
        metadata = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
        node = str(metadata.get("langgraph_node") or "")
        chunk_type = chunk.get("type")

        if chunk_type == "tool":
            return self._on_tool_message(namespace, node, chunk)
        if chunk_type in _AI_TYPES:
            return self._on_ai_chunk(namespace, node, chunk)
        if chunk_type in ("human", "system"):
            return self._emit_whole_message(
                namespace, node, chunk, role=str(chunk_type)
            )
        return []

    def _on_ai_chunk(self, namespace: list[str], node: str, chunk: dict) -> list[dict]:
        key = (_ns_key(namespace), node)
        chunk_id = chunk.get("id")
        out: list[dict] = []

        open_msg = self._open.get(key)
        if open_msg is not None and chunk_id is not None and open_msg.id != chunk_id:
            out.extend(self._finish_message(key))
            open_msg = None
        if open_msg is None:
            open_msg = _OpenMessage(id=chunk_id, role="ai")
            self._open[key] = open_msg
            out.append(
                ev.message_start(
                    namespace, node, role="ai", message_id=chunk_id or f"{node}-ai"
                )
            )

        # Text (string content or content-block list)
        content = chunk.get("content")
        if isinstance(content, str) and content:
            out.extend(self._text_delta(namespace, node, open_msg, "text", content))
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and part.get("text"):
                    out.extend(
                        self._text_delta(
                            namespace, node, open_msg, "text", part["text"]
                        )
                    )
                elif part.get("type") == "thinking" and part.get("thinking"):
                    out.extend(
                        self._reasoning_delta(
                            namespace, node, open_msg, part["thinking"]
                        )
                    )

        # DeepSeek reasoning rides additional_kwargs, not content.
        kwargs = chunk.get("additional_kwargs")
        if isinstance(kwargs, dict):
            reasoning = kwargs.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                out.extend(self._reasoning_delta(namespace, node, open_msg, reasoning))

        # Streamed tool-call argument chunks.
        for tc_chunk in chunk.get("tool_call_chunks") or []:
            if not isinstance(tc_chunk, dict):
                continue
            out.extend(self._tool_call_chunk(namespace, node, open_msg, tc_chunk))

        # Complete tool calls (whole-message providers / synthetic messages).
        for tc in chunk.get("tool_calls") or []:
            if isinstance(tc, dict) and tc.get("id"):
                known = {t.get("id") for t in open_msg.tool_calls}
                if tc["id"] not in known:
                    open_msg.tool_calls.append(tc)

        if isinstance(chunk.get("usage_metadata"), dict):
            open_msg.usage = chunk["usage_metadata"]
        return out

    def _text_delta(
        self,
        namespace: list[str],
        node: str,
        msg: _OpenMessage,
        block_key: str,
        text: str,
    ) -> list[dict]:
        out = []
        index = msg.blocks.get(block_key)
        if index is None:
            index = msg.next_index
            msg.next_index += 1
            msg.blocks[block_key] = index
            out.append(
                ev.content_block_start(
                    namespace, node, index=index, content={"type": "text", "text": text}
                )
            )
        else:
            out.append(
                ev.content_block_delta(
                    namespace,
                    node,
                    index=index,
                    delta={"type": "text-delta", "text": text},
                )
            )
        return out

    def _reasoning_delta(
        self, namespace: list[str], node: str, msg: _OpenMessage, reasoning: str
    ) -> list[dict]:
        out = []
        index = msg.blocks.get("reasoning")
        if index is None:
            index = msg.next_index
            msg.next_index += 1
            msg.blocks["reasoning"] = index
            out.append(
                ev.content_block_start(
                    namespace,
                    node,
                    index=index,
                    content={"type": "reasoning", "reasoning": reasoning},
                )
            )
        else:
            out.append(
                ev.content_block_delta(
                    namespace,
                    node,
                    index=index,
                    delta={"type": "reasoning-delta", "reasoning": reasoning},
                )
            )
        return out

    def _tool_call_chunk(
        self, namespace: list[str], node: str, msg: _OpenMessage, tc_chunk: dict
    ) -> list[dict]:
        block_key = f"tc:{tc_chunk.get('index', 0)}"
        acc = msg.tool_call_chunks.get(block_key)
        content = {
            "type": "tool_call_chunk",
            "id": tc_chunk.get("id"),
            "name": tc_chunk.get("name"),
            "args": tc_chunk.get("args") or "",
        }
        if acc is None:
            index = msg.next_index
            msg.next_index += 1
            msg.blocks[block_key] = index
            msg.tool_call_chunks[block_key] = {
                "id": tc_chunk.get("id"),
                "name": tc_chunk.get("name"),
                "args": tc_chunk.get("args") or "",
            }
            return [
                ev.content_block_start(namespace, node, index=index, content=content)
            ]
        # Accumulate server-side (for the finalized tool_call block) and send
        # the raw-block merge form the client concatenates.
        acc["id"] = acc["id"] or tc_chunk.get("id")
        acc["name"] = acc["name"] or tc_chunk.get("name")
        acc["args"] = (acc["args"] or "") + (tc_chunk.get("args") or "")
        return [
            ev.content_block_merge(
                namespace, node, index=msg.blocks[block_key], content=content
            )
        ]

    def _on_tool_message(
        self, namespace: list[str], node: str, chunk: dict
    ) -> list[dict]:
        """A ToolMessage: a tool-role message on `messages` + tools lifecycle."""
        out: list[dict] = []
        tool_call_id = chunk.get("tool_call_id")
        message_id = chunk.get("id") or (
            f"tool-{tool_call_id}" if tool_call_id else "tool-result"
        )
        out.append(
            ev.message_start(
                namespace,
                node,
                role="tool",
                message_id=message_id,
                tool_call_id=tool_call_id,
            )
        )
        out.append(
            ev.content_block_start(
                namespace,
                node,
                index=0,
                content={"type": "text", "text": _text_of(chunk.get("content"))},
            )
        )
        out.append(ev.message_finish(namespace, node))
        out.extend(self._tool_result_events(namespace, node, chunk))
        return out

    def _tool_result_events(
        self, namespace: list[str], node: str, message: dict
    ) -> list[dict]:
        """`tools` channel completion for a ToolMessage dict, deduped by id."""
        tool_call_id = message.get("tool_call_id")
        if not tool_call_id or tool_call_id in self._tool_finished_ids:
            return []
        self._tool_finished_ids.add(tool_call_id)
        if message.get("status") == "error":
            return [
                ev.tool_error(
                    namespace,
                    node,
                    tool_call_id=tool_call_id,
                    message=_text_of(message.get("content")),
                )
            ]
        finished = ev.tool_finished(
            namespace, node, tool_call_id=tool_call_id, output=message.get("content")
        )
        # Extension field: MCP tool artifacts (structured content, app resource
        # URIs) ride along for the MCP-app widgets. `Extensible` allows it.
        if message.get("artifact") is not None:
            finished["params"]["data"]["artifact"] = message["artifact"]
        return [finished]

    # --- updates mode ----------------------------------------------------------

    def _on_updates(self, namespace: list[str], data: Any) -> list[dict]:
        """Updates are not forwarded; they mark superstep boundaries (closing
        open messages) and are the authoritative source for `tool-started`."""
        out = self._finish_namespace(namespace)
        if not isinstance(data, dict):
            return out
        for node_name, node_data in data.items():
            if not isinstance(node_data, dict):
                continue
            messages = node_data.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if message.get("type") in _AI_TYPES:
                    for tc in message.get("tool_calls") or []:
                        out.extend(self._tool_started_event(namespace, node_name, tc))
                elif message.get("type") == "tool":
                    out.extend(self._tool_result_events(namespace, node_name, message))
        return out

    def _tool_started_event(
        self, namespace: list[str], node: str, tc: Any
    ) -> list[dict]:
        if not isinstance(tc, dict) or not tc.get("id"):
            return []
        if tc["id"] in self._tool_started_ids:
            return []
        self._tool_started_ids.add(tc["id"])
        return [
            ev.tool_started(
                namespace,
                node,
                tool_call_id=tc["id"],
                tool_name=tc.get("name") or "tool",
                tool_input=tc.get("args"),
            )
        ]

    # --- values mode -----------------------------------------------------------

    def _on_values(self, namespace: list[str], data: Any) -> list[dict]:
        out = self._finish_namespace(namespace)
        if not isinstance(data, dict):
            return out
        if namespace:
            out.extend(self._namespaced_values(namespace, data))
            return out

        interrupts = data.get("__interrupt__")
        trimmed = {
            k: v for k, v in data.items() if k not in ("messages", "__interrupt__")
        }
        out.append(ev.values_event([], trimmed))
        # Tool lifecycle backstop: values are the one event guaranteed per
        # superstep, so a run whose `updates` were trimmed from the log tail
        # (MAXLEN) still gets its tool-started/finished pairs.
        for message in data.get("messages") or []:
            if not isinstance(message, dict):
                continue
            if message.get("type") in _AI_TYPES:
                for tc in message.get("tool_calls") or []:
                    out.extend(self._tool_started_event([], "", tc))
            elif message.get("type") == "tool":
                out.extend(self._tool_result_events([], "", message))
        if isinstance(interrupts, list):
            for interrupt in interrupts:
                if not isinstance(interrupt, dict):
                    continue
                interrupt_id = interrupt.get("id")
                if interrupt_id is None or interrupt_id in self._interrupt_ids:
                    continue
                self._interrupt_ids.add(interrupt_id)
                out.append(
                    ev.input_requested(
                        [], interrupt_id=interrupt_id, payload=interrupt.get("value")
                    )
                )
        return out

    def _namespaced_values(self, namespace: list[str], data: dict) -> list[dict]:
        """Subagent values: strip messages, except the first snapshot keeps the
        first human message — the client binds `tools:<task-id>` namespaces to
        their `task` tool call by that text."""
        binding_key = f"values-bound:{_ns_key(namespace)}"
        trimmed: dict[str, Any] = {
            k: v for k, v in data.items() if k not in ("messages", "__interrupt__")
        }
        if binding_key not in self._seen_namespaces:
            self._seen_namespaces.add(binding_key)
            first_human = next(
                (
                    m
                    for m in data.get("messages") or []
                    if isinstance(m, dict) and m.get("type") == "human"
                ),
                None,
            )
            if first_human is not None:
                trimmed["messages"] = [first_human]
        return [ev.values_event(namespace, trimmed)]

    # --- message finishing -------------------------------------------------------

    def _finish_namespace(self, namespace: list[str]) -> list[dict]:
        ns_key = _ns_key(namespace)
        out: list[dict] = []
        for key in [k for k in self._open if k[0] == ns_key]:
            out.extend(self._finish_message(key))
        return out

    def _finish_all_open(self) -> list[dict]:
        out: list[dict] = []
        for key in list(self._open):
            out.extend(self._finish_message(key))
        return out

    def _finish_message(self, key: tuple[str, str]) -> list[dict]:
        msg = self._open.pop(key, None)
        if msg is None:
            return []
        ns_key, node = key
        namespace = ns_key.split("|") if ns_key else []
        out: list[dict] = []

        # Finalize streamed tool-call chunks into clean `tool_call` blocks —
        # the client's `toolCalls` view is fed by `content-block-finish`.
        finalized = dict(msg.tool_call_chunks)
        for tc in msg.tool_calls:
            block_key = f"tc:whole:{tc.get('id')}"
            if any(acc.get("id") == tc.get("id") for acc in finalized.values()):
                continue
            index = msg.next_index
            msg.next_index += 1
            msg.blocks[block_key] = index
            finalized[block_key] = {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "args": tc.get("args"),
                "_parsed": True,
            }
        for block_key, acc in finalized.items():
            args: Any = acc.get("args")
            if not acc.pop("_parsed", False):
                try:
                    args = json.loads(args) if args else {}
                except (TypeError, ValueError):
                    args = {}
            out.append(
                ev.content_block_finish(
                    namespace,
                    node,
                    index=msg.blocks[block_key],
                    content={
                        "type": "tool_call",
                        "id": acc.get("id"),
                        "name": acc.get("name") or "tool",
                        "args": args if isinstance(args, dict) else {},
                    },
                )
            )
        out.append(ev.message_finish(namespace, node, usage=msg.usage))
        return out

    def _emit_whole_message(
        self, namespace: list[str], node: str, chunk: dict, *, role: str
    ) -> list[dict]:
        """A complete non-AI message (human/system) delivered on the messages
        stream — emit it as a closed start/block/finish triple."""
        message_id = chunk.get("id") or f"{role}-message"
        return [
            ev.message_start(namespace, node, role=role, message_id=message_id),
            ev.content_block_start(
                namespace,
                node,
                index=0,
                content={"type": "text", "text": _text_of(chunk.get("content"))},
            ),
            ev.message_finish(namespace, node),
        ]
