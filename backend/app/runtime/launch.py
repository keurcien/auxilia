"""`launch()` — the one seam every ingress crosses to start a run.

A user message reaches auxilia four ways: the web client's protocol commands
(`app/runtime/api/`), the `/runs` endpoints, Slack, and a trigger firing. Each
one used to carry its own copy of the pre-flight choreography — release the
request connection, probe OAuth, check the model — in a different subset.
They now build a `LaunchRequest` and call `launch`, which owns the sequence:

1. `input` xor `command`; an addressed HITL resume is canonicalised against
   the thread's checkpoint (stale → `StaleApprovalError`, a 409 to whoever
   clicked, before any run exists).
2. The thread must exist; its model must be available and its sandboxes
   reachable (`preflight.ensure_launchable`).
3. Every OAuth server the graph binds must be connected for the actor
   (`preflight.required_oauth_url`), else `OAuthAuthorizationRequired(url)`.
4. `RunService.create` inserts the pending run under the per-thread mutex.

`launch` opens its own short sessions, so it has no "commit yours first"
clause: an ingress does its authorisation reads, commits, and hands off ids.
How a refusal is rendered stays at the ingress — a 401 body, a Slack reply, a
rejected trigger — because that is where the channels genuinely differ.
"""

from dataclasses import dataclass

from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import DomainValidationError, NotFoundError, StaleApprovalError
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.model_providers.service import ModelService
from app.runtime.hitl import (
    build_resume_command,
    is_addressed_resume,
    load_interrupt_scope,
)
from app.runtime.preflight import ensure_launchable, required_oauth_url
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import RunService
from app.runtime.runs.state import MultitaskStrategy
from app.threads.repository import ThreadRepository


@dataclass(frozen=True, kw_only=True)
class LaunchRequest:
    """What an ingress knows about the turn it wants to run.

    `user_id` is the actor whose MCP credentials the run uses — the thread
    owner for chat surfaces, the trigger owner for a firing. `delivery` is an
    opaque push-target descriptor (e.g. Slack channel/thread) the worker hands
    to a delivery consumer; None means a pull subscriber rides the event log.
    """

    thread_id: str
    user_id: str
    input: dict | None = None
    command: dict | None = None
    trigger: str | None = None
    config_overrides: dict | None = None
    output_schema: dict | None = None
    delivery: dict | None = None
    multitask_strategy: MultitaskStrategy = "reject"


async def launch(
    request: LaunchRequest,
    *,
    runs: RunService | None = None,
    preflight_oauth: bool = True,
) -> RunDB:
    """Gate the request and create the pending run. See the module docstring.

    `preflight_oauth=False` skips gate 3 for an ingress that has already
    answered the OAuth question itself (Slack's readiness check, the trigger
    "Run now" button) or has nobody to answer to (the scanner): those runs
    still hit the worker's net, which fails them fast with the reconnect
    error the surfaces know how to render.
    """
    if request.input is not None and request.command is not None:
        raise DomainValidationError("Provide either input or command, not both.")
    command = request.command
    if command is not None:
        command = await _canonical_command(request.thread_id, command)
    # Warm the whitelist cache before taking a pooled connection: on a
    # cold/expired catalog cache the CDN fetch can take seconds, and it must
    # not hold a DB session (pool exhaustion under load).
    await ModelService.list_whitelisted()
    async with AsyncSessionLocal() as db:
        thread = await ThreadRepository(db).get(request.thread_id)
        if thread is None:
            raise NotFoundError("Thread not found")
        spec = await ensure_launchable(db, thread)
        auth_url = (
            await required_oauth_url(db, thread.agent_id, request.user_id, spec=spec)
            if preflight_oauth
            else None
        )
    if auth_url is not None:
        raise OAuthAuthorizationRequired(auth_url)
    return await (runs or RunService()).create(
        thread_id=request.thread_id,
        user_id=request.user_id,
        input=request.input,
        command=command,
        trigger=request.trigger,
        config_overrides=request.config_overrides,
        output_schema=request.output_schema,
        delivery=request.delivery,
        multitask_strategy=request.multitask_strategy,
    )


async def _canonical_command(thread_id: str, command: dict) -> dict:
    """Resolve an addressed HITL resume against the thread's checkpoint.

    An addressed resume (``{"resume": {"interrupt_id": ..., "decisions":
    [...]}}``) is validated and ordered here — while still inside the
    initiating context, so a stale approval surfaces as a 409 to whoever
    clicked instead of failing a background run — and stored in its
    canonical, replayable form (`hitl.build_resume_command`). Anything
    else passes through untouched: the legacy positional resume, or a
    replayed canonical command. Runs before any DB session opens, so the
    checkpoint read never holds a pooled connection.
    """
    if not is_addressed_resume(command.get("resume")):
        return command
    # Addressed by id: with parallel subagents paused together the resume
    # must target the one the client answered, not the first pending.
    interrupt_id = command["resume"].get("interrupt_id")
    async with get_checkpointer() as checkpointer:
        scope = await load_interrupt_scope(
            checkpointer,
            thread_id,
            interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
        )
    if scope is None:
        raise StaleApprovalError(
            "No approval is pending on this thread."
            if interrupt_id is None
            else "This approval request was already handled."
        )
    # The decisions are matched against the checkpoint that holds the
    # gated tool calls — a subagent's own when a subagent paused.
    return build_resume_command(scope.root, command["resume"], scope.state)
