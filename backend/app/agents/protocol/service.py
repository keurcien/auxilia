"""ProtocolService — commands, the event-stream session, and thread state.

A thin orchestration layer over `RunService` and the run event log:

- `dispatch` maps protocol commands onto the existing run verbs
  (`run.start` → `RunService.create(input=…)`, `input.respond` →
  `RunService.create(command={"resume": …})` with the checkpoint-keyed
  canonicalization from PR #307).
- `stream_events` serves one SSE session: it resolves the thread's newest
  run, relays its stored protocol events (filtered by the session's sink,
  stamped with `event_id`/`seq` derived from the log entry ids — see
  `wire.py`), then follows onto newer runs as they appear. A session is
  thread-scoped and lives until the client closes it (the client's lifecycle
  watcher holds one open for the thread's whole life).
- `thread_state` builds the LangGraph-shaped `{values, next, tasks}` snapshot
  the client hydrates from; `next`/`tasks[].interrupts` drive its
  "is this thread active" gate, so they must reflect the active run and any
  pending HITL interrupt.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import Redis

from app.agents.hitl import pending_interrupt
from app.agents.protocol.events import terminal_lifecycle
from app.agents.protocol.filter import StreamFilter
from app.agents.protocol.messages import serialize_message
from app.agents.protocol.schemas import EventStreamBody, ProtocolCommand
from app.agents.protocol.wire import decode_event, frame, seq_for_entry
from app.agents.runs.events import RunEventStream
from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.state import is_terminal
from app.database import get_checkpointer
from app.exceptions import DomainValidationError
from app.redis_client import get_redis


logger = logging.getLogger(__name__)

_KEEP_ALIVE = ": keep-alive\n\n"
_IDLE_POLL_SECONDS = 1.0
_BLOCK_MS = 5000


class ProtocolService:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()
        self.runs = RunService(self.redis)

    # --- commands -------------------------------------------------------------

    async def dispatch(
        self, thread_id: str, user_id: str, command: ProtocolCommand
    ) -> dict:
        """Execute one protocol command; returns the response envelope.

        Domain failures (stale approval → 409, model unavailable → 409, …)
        propagate as the same HTTP errors the run endpoints raise — the
        frontend's fetch layer already speaks them. Only protocol-level
        conditions (unknown/unsupported methods) come back as protocol
        `ErrorResponse` bodies.
        """
        if command.method == "run.start":
            run = await self._run_start(thread_id, user_id, command.params)
            return _success(command.id, {"run_id": run.id})
        if command.method == "input.respond":
            await self._input_respond(thread_id, user_id, command.params)
            return _success(command.id, {})
        known_unsupported = {
            "input.inject",
            "agent.getTree",
            "state.get",
            "state.listCheckpoints",
            "state.fork",
            "subscription.subscribe",
            "subscription.unsubscribe",
            "subscription.reconnect",
        }
        if command.method in known_unsupported:
            return _error(
                command.id,
                "not_supported",
                f"{command.method} is not supported by this server.",
            )
        return _error(
            command.id, "unknown_command", f"Unknown method {command.method!r}."
        )

    async def _run_start(self, thread_id: str, user_id: str, params: dict) -> RunDB:
        # Validate the raw value before defaulting — a falsey non-object
        # (0, "", false) must be rejected, not coerced to {}.
        raw_config = params.get("config")
        if raw_config is not None and not isinstance(raw_config, dict):
            raise DomainValidationError("run.start `config` must be an object.")
        config = raw_config or {}
        configurable = dict(config.get("configurable") or {})
        configurable.pop("thread_id", None)
        trigger = configurable.pop("trigger", None)
        config_overrides = (
            {**config, "configurable": configurable} if configurable else None
        )
        return await self.runs.create(
            thread_id=thread_id,
            user_id=user_id,
            input=params.get("input"),
            trigger=trigger,
            config_overrides=config_overrides,
        )

    async def _input_respond(self, thread_id: str, user_id: str, params: dict) -> RunDB:
        """Map `input.respond` onto a resume run.

        The single-response form carries `{interrupt_id, response}`; the
        batched form carries `responses: [...]` — auxilia threads pause on at
        most one interrupt, so the batch must have exactly one entry. The
        `response` payload is the HITL decisions object the web client already
        builds (`{"decisions": [...]}`); `RunService.create` canonicalizes and
        stale-checks it against the checkpoint (409 on a stale approval).
        """
        responses = params.get("responses")
        if responses is not None:
            if not isinstance(responses, list) or len(responses) != 1:
                raise DomainValidationError(
                    "input.respond supports exactly one response per command."
                )
            params = responses[0] if isinstance(responses[0], dict) else {}
        interrupt_id = params.get("interrupt_id")
        response = params.get("response")
        if response is None and not interrupt_id:
            raise DomainValidationError(
                "input.respond requires a response or an interrupt_id."
            )
        response_map = response if isinstance(response, dict) else None
        decisions = response_map.get("decisions") if response_map else None
        if (
            isinstance(interrupt_id, str)
            and interrupt_id
            and response_map is not None
            and isinstance(decisions, list)
            and all(
                isinstance(d, dict) and isinstance(d.get("tool_call_id"), str)
                for d in decisions
            )
        ):
            resume: Any = {"interrupt_id": interrupt_id, **response_map}
        else:
            # No usable interrupt id (pre-#307 checkpoints), positional
            # decisions (tool calls persisted without ids), or a free-form
            # resume value — pass through un-addressed; the graph still
            # targets the single pending interrupt.
            resume = response
        return await self.runs.create(
            thread_id=thread_id, user_id=user_id, command={"resume": resume}
        )

    # --- event stream -----------------------------------------------------------

    async def stream_events(
        self, thread_id: str, body: EventStreamBody
    ) -> AsyncGenerator[str, None]:
        """One protocol SSE session: replay the newest run, then follow newer
        runs as they appear, until the client disconnects."""
        sink = StreamFilter.from_request(body.channels, body.namespaces, body.depth)
        current: RunDB | None = None
        while True:
            run = await self._next_run(thread_id, after=current)
            if run is None:
                yield _KEEP_ALIVE
                await asyncio.sleep(_IDLE_POLL_SECONDS)
                continue
            current = run
            async for sse in self._stream_run(run, sink, since=body.since):
                yield sse

    async def _next_run(self, thread_id: str, after: RunDB | None) -> RunDB | None:
        """The newest run of the thread — or, when we already served `after`,
        the oldest run created after it (so a session follows runs in order)."""
        records = await self.runs.list_for_thread(thread_id)  # newest first
        if after is None:
            return records[0] if records else None
        cutoff = after.created_at
        if cutoff is None:  # pre-flush record; only possible in tests
            return None
        newer = [
            r for r in records if r.created_at is not None and r.created_at > cutoff
        ]
        return newer[-1] if newer else None

    async def _stream_run(
        self, run: RunDB, sink: StreamFilter, *, since: int | None
    ) -> AsyncGenerator[str, None]:
        """Relay one run's stored events through the session filter.

        Each log entry holds one protocol event; its entry id is the client's
        `event_id` and encodes its `seq`, so a reopened session reproduces
        identical cursors and the client's dedup does the rest. Entries this
        codec doesn't own (a legacy-format log from a run in flight during
        the deploy) are skipped — the `_END` marker still terminates them.
        """
        events = RunEventStream(run.id, self.redis)

        def relay(
            event: dict, entry_id: str, *, bypass_since: bool = False
        ) -> str | None:
            if (
                not bypass_since
                and since is not None
                and seq_for_entry(entry_id) <= since
            ):
                return None
            if not sink.matches(event):
                return None
            return frame(event, entry_id=entry_id)

        def synthetic_terminal(record: RunDB) -> str | None:
            # The synthetic entry id yields seq 0, so it must bypass the
            # `since` filter or a reconnecting client never settles.
            return relay(
                terminal_lifecycle(record.status.value, error=record.error),
                f"{run.id}-x",
                bypass_since=True,
            )

        if not await events.exists():
            record = await self.runs.get(run.id)
            if is_terminal(record.status):
                # The log expired — synthesize the terminal lifecycle from the
                # durable record, which outlives the log.
                if (sse := synthetic_terminal(record)) is not None:
                    yield sse
                return

        cursor = "0"
        while True:
            batch = await events.read_batch_with_ids(cursor, block_ms=_BLOCK_MS)
            if batch is None:
                record = await self.runs.get(run.id)
                if is_terminal(record.status):
                    # Worker died between the DB commit and the terminal entry.
                    if (sse := synthetic_terminal(record)) is not None:
                        yield sse
                    return
                yield _KEEP_ALIVE
                continue
            cursor, entries, ended = batch
            for entry_id, raw, _is_end in entries:
                event = decode_event(raw)
                if event is None:
                    continue
                if (sse := relay(event, entry_id)) is not None:
                    yield sse
            if ended:
                return

    # --- thread state -------------------------------------------------------------

    async def thread_state(self, thread_id: str) -> dict:
        """LangGraph-shaped state snapshot for client hydration."""
        async with get_checkpointer() as checkpointer:
            checkpoint_tuple = await checkpointer.aget_tuple(
                config={"configurable": {"thread_id": thread_id}}
            )
        values: dict[str, Any] = {"messages": []}
        interrupt = None
        if checkpoint_tuple is not None:
            channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
            values = {
                "messages": [
                    serialize_message(m) for m in channel_values.get("messages", [])
                ]
            }
            if todos := channel_values.get("todos"):
                values["todos"] = todos
            if (structured := channel_values.get("structured_response")) is not None:
                values["structured_response"] = structured
            interrupt = pending_interrupt(checkpoint_tuple)

        active = await self.runs.get_active(thread_id)
        # `next` non-empty ⇔ a run is executing or a resume is awaited — the
        # client's activity gate opens its live pumps only then.
        next_nodes = ["agent"] if active is not None or interrupt is not None else []
        tasks = []
        if interrupt is not None:
            tasks.append(
                {
                    "id": interrupt.id or "interrupt",
                    "name": "agent",
                    "interrupts": [{"id": interrupt.id, "value": interrupt.value}],
                }
            )
        return {"values": values, "next": next_nodes, "tasks": tasks}


def _success(command_id: int, result: dict) -> dict:
    return {"type": "success", "id": command_id, "result": result}


def _error(command_id: int, code: str, message: str) -> dict:
    return {"type": "error", "id": command_id, "error": code, "message": message}
