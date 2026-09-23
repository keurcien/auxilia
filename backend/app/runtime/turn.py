"""Stage 4 of executing a run: drive one turn and yield protocol events.

`run_turn(graph, resolved, live, turn)` takes the assembled graph and the
turn's replay tuple (`TurnInput`: what `RunDB` stores) and drives langgraph's
`astream_events(version="v3")`, which emits the Agent Streaming Protocol
grammar natively for every namespace (subagents included); `ProtocolEmitter`
applies the publish-side policies the web client's contract needs. Input
parsing, the regeneration fork, the `structured_response` reset and the
recursion fallback all live here, and all take their handles as arguments —
so a test runs them with a scripted model and a fake checkpointer, no
network anywhere.

A graph failure propagates to the caller — the worker finalizes the run as
`error` and publishes the terminal lifecycle with the root-cause message.

Also here: reading a finished turn's result back off the checkpoint
(`read_run_result`), for the synchronous `/runs/invoke` consumer.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    convert_to_messages,
)
from langgraph.errors import GraphRecursionError
from langgraph.stream.transformers import UpdatesTransformer
from langgraph.types import Command

from app.database import get_checkpointer
from app.exceptions import DomainValidationError
from app.runtime.checkpoints import get_checkpoint_state
from app.runtime.middleware.structured_output import is_structured_output_artifact
from app.runtime.protocol.emit import ProtocolEmitter
from app.runtime.resolve import ResolvedRun
from app.runtime.resources import LiveResources
from app.runtime.runs.models import RunDB
from app.runtime.settings import agent_settings


logger = logging.getLogger(__name__)

RECURSION_LIMIT_MESSAGE = (
    "I reached my step limit for this turn. Send any follow-up message "
    '(e.g. "continue") and I\'ll pick up where I left off.'
)

SANDBOX_REPLACED_NOTICE = (
    "[Host notice] The sandbox used earlier in this conversation no longer "
    "exists and had no snapshot. A new, empty sandbox has been created: files "
    "written earlier are gone, so recreate anything you need before using it."
)


@dataclass(frozen=True, kw_only=True)
class TurnInput:
    """One turn's replay parameters — exactly what the run record stores.

    `input` is the graph input (e.g. `{"messages": [{"type": "human", …}]}`)
    or None for a resume; `command` a LangGraph Command dict
    (`{"resume": …}`) for a HITL resume; `trigger` "regenerate-message" to
    redo the last turn; `output_schema` a JSON Schema for a
    `structured_response` (read back via `read_run_result`).
    """

    input: dict | None = None
    command: dict | None = None
    trigger: str | None = None
    config_overrides: dict | None = None
    output_schema: dict | None = None

    @classmethod
    def from_record(cls, record: RunDB) -> "TurnInput":
        return cls(
            input=record.input,
            command=record.command,
            trigger=record.trigger,
            config_overrides=record.config_overrides,
            output_schema=record.output_schema,
        )


@dataclass(frozen=True)
class RegenerationPoint:
    """Where a regeneration restarts the thread from, and with what.

    ``checkpoint_id`` is the checkpoint to fork from — the last one *before*
    the turn being redone. ``None`` means the turn being redone was the
    thread's first, so there is nothing earlier to fork from and the thread
    restarts from scratch instead. ``message`` is the user message that
    opened the turn, re-sent as the fork's input under its original id.
    """

    checkpoint_id: str | None
    message: HumanMessage | None


async def get_regeneration_point(graph, config: dict) -> RegenerationPoint | None:
    """Where to restart from when regenerating the last answer, or ``None``
    when the thread has no turn to redo.

    The turn's ``source="input"`` checkpoint is found in one history read; it
    holds the user's message as a pending write. The fork target is that
    checkpoint's **parent** — the end of the previous turn — not the input
    checkpoint itself, and the message is re-sent as fresh input. Forking from
    the input checkpoint would be the obvious choice and is wrong under
    ``DeepAgentState``: langgraph copies the loaded checkpoint's pending
    writes onto the fork checkpoint it creates, and the ``DeltaChannel``
    replay then sees the user's message twice — once under each — so every
    later turn (and every reader) shows the question duplicated. The parent
    has no pending writes, so nothing is copied. Under ``add_messages`` both
    forks are equivalent, since it forks from stored values, not writes.
    """
    async for state in graph.aget_state_history(
        config, filter={"source": "input"}, limit=1
    ):
        # The input snapshot's values are the state *before* the message was
        # applied (it sits in the snapshot's pending writes), so the turn's
        # message is read off the thread's latest state instead: its last
        # human message.
        latest = await graph.aget_state(config)
        message = next(
            (
                m
                for m in reversed(latest.values.get("messages", []))
                if isinstance(m, HumanMessage)
            ),
            None,
        )
        parent = state.parent_config
        if parent is None:
            return RegenerationPoint(checkpoint_id=None, message=message)
        return RegenerationPoint(
            checkpoint_id=parent["configurable"]["checkpoint_id"], message=message
        )
    return None


async def run_turn(
    graph, resolved: ResolvedRun, live: LiveResources, turn: TurnInput
) -> AsyncIterator[dict]:
    """Run one turn, yielding Agent Streaming Protocol events (`{method,
    params}` dicts — see `app/runtime/protocol/emit.py`)."""
    stream_input = _resolve_input(turn.input, turn.command)
    if live.sandbox_replaced:
        stream_input = _with_host_notice(
            stream_input, SANDBOX_REPLACED_NOTICE, "sandbox_replaced"
        )
    config, stream_input = await _resolve_config(
        graph,
        live.checkpointer,
        resolved,
        trigger=turn.trigger,
        config_overrides=turn.config_overrides,
        resolved_input=stream_input,
    )
    if turn.output_schema is not None and turn.command is None:
        # `structured_response` is a persistent channel: if this turn's
        # formatting never runs (e.g. recursion fallback), a previous
        # turn's value would otherwise be read back as this run's result.
        state = await graph.aget_state(config)
        if state.values.get("structured_response") is not None:
            await graph.aupdate_state(config, {"structured_response": None})
    # The call itself must be awaited; iterating the returned run stream is
    # what drives the graph (no background task). The context manager aborts
    # the graph iterator on an early exit — the worker's cancel lands here as
    # a CancelledError. `updates` is opt-in: the emitter reads each node's
    # written messages off it to complete tool calls that never ran (see
    # ProtocolEmitter).
    run = await graph.astream_events(
        stream_input,
        config=config,
        version="v3",
        transformers=[UpdatesTransformer],
    )
    emitter = ProtocolEmitter()
    try:
        async with run:
            async for event in emitter.stream(run):
                yield event
    except GraphRecursionError:
        ai_msg = await _persist_recursion_fallback(graph, config)
        state = await graph.aget_state(config)
        for event in emitter.synthetic_ai_message(ai_msg, state.values):
            yield event


def _stream_config(resolved: ResolvedRun) -> dict:
    return {
        "configurable": {"thread_id": resolved.thread.id},
        "recursion_limit": agent_settings.recursion_limit,
        "callbacks": resolved.callbacks,
        "metadata": resolved.metadata,
    }


def _resolve_input(agent_input: dict | None, command: dict | None):
    """Resolve raw input/command dicts into the value to pass to the graph.

    The message dicts come from a client (the chat UI, a trigger, Slack), so
    a malformed one is a bad request, not a server fault — `convert_to_messages`
    rejects an unknown role instead of silently filing it as a user turn.
    It signals rejection with whatever fits the shape it was handed:
    `ValueError` for an unknown role or a dict missing `content`,
    `NotImplementedError` for an item that is not a message at all (a bare
    number, `None`, a nested list). All of them are the client's fault.
    """
    if command is not None:
        return Command(resume=command.get("resume"))
    raw = agent_input.get("messages", []) if agent_input else []
    if not isinstance(raw, list):
        raise DomainValidationError("Invalid run input: `messages` must be a list")
    try:
        messages = convert_to_messages(raw)
    except (ValueError, TypeError, KeyError, NotImplementedError) as e:
        raise DomainValidationError(f"Invalid run input: {e}") from e
    return {"messages": messages}


async def _resolve_config(
    graph,
    checkpointer,
    resolved: ResolvedRun,
    *,
    trigger: str | None,
    config_overrides: dict | None,
    resolved_input: Any,
) -> tuple[dict, Any]:
    """Build the run config, applying overrides and regeneration logic.

    Returns the config and the input to run with. Regenerating forks the
    thread from before its last turn (see `get_regeneration_point`) and
    re-sends the message that opened it. The client submits *no* input
    for a regeneration — the documented `submit(null, …)` shape, so it
    echoes nothing optimistically and the page keeps the question in
    place while only the answer changes — and the server supplies the
    message, under its original id, from the turn's input checkpoint. A
    client that does re-send the message (Slack, older pages) is honoured
    as-is. When the turn was the thread's first there is no earlier
    checkpoint: the thread's checkpoints are wiped and the message starts
    it over — the same outcome, with no history to fork from.
    """
    config = _stream_config(resolved)
    if config_overrides and config_overrides.get("configurable"):
        config["configurable"].update(config_overrides["configurable"])
    if trigger == "regenerate-message":
        point = await get_regeneration_point(graph, config)
        has_input = isinstance(resolved_input, dict) and bool(
            resolved_input.get("messages")
        )
        if point is None or (not has_input and point.message is None):
            if not has_input:
                raise DomainValidationError("Nothing to regenerate on this thread.")
        else:
            if not has_input:
                resolved_input = {"messages": [point.message]}
            if point.checkpoint_id is None:
                await checkpointer.adelete_thread(resolved.thread.id)
            else:
                config["configurable"]["checkpoint_id"] = point.checkpoint_id
    return config, resolved_input


async def _persist_recursion_fallback(graph, config) -> AIMessage:
    """Persist a synthetic AI message after a GraphRecursionError so the
    next turn can pick up where we left off. Returns the message."""
    logger.info("Graph recursion limit reached; persisting synthetic AI message")
    ai_msg = AIMessage(content=RECURSION_LIMIT_MESSAGE, id=str(uuid4()))
    await graph.aupdate_state(config, {"messages": [ai_msg]})
    return ai_msg


def _with_host_notice(resolved_input, text: str, kind: str):
    """Prepend a host-authored message to a turn's input so it lands in the
    checkpoint ahead of the user's message.

    The user role is the one channel every provider accepts mid-history and
    every harness uses for this (LangChain's summaries, OpenHands' environment
    events, Claude Code's reminders); `name`/`host_notice` let the chat render
    it as an event rather than as the user, and Slack skip it. A resume
    (`Command`) carries no messages to prepend to and is left alone.
    """
    if not isinstance(resolved_input, dict):
        return resolved_input
    notice = HumanMessage(
        content=text, name="host", additional_kwargs={"host_notice": kind}
    )
    return {**resolved_input, "messages": [notice, *resolved_input.get("messages", [])]}


def extract_invoke_result(
    messages: list, structured_response: dict | None = None
) -> dict:
    """Project a turn's final messages into the invoke response shape.

    Skips formatting-turn artifacts so `content` is the prose answer on every
    provider path; the parsed object travels in its own field. Used by the
    durable path's `read_run_result`.
    """
    last = next(
        (m for m in reversed(messages) if not is_structured_output_artifact(m)),
        None,
    )
    return {
        "content": _extract_text(last) if last else "",
        "structured_response": structured_response,
    }


async def read_run_result(thread_id: str) -> dict:
    """Read a thread's final-turn result from its checkpoint (out-of-request).

    The durable runtime streams a run to its event log rather than returning a
    value, so the synchronous `/runs/invoke` consumer reads the answer back from
    the LangGraph checkpoint once the run is terminal.
    """
    async with get_checkpointer() as checkpointer:
        state = await get_checkpoint_state(checkpointer, thread_id)
    return extract_invoke_result(state.messages, state.structured_response)


def _extract_text(message: BaseMessage) -> str:
    """Extract the text content from an AIMessage, skipping thinking blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
