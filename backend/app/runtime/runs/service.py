"""RunService — the public API of the durable runtime.

Orchestrates Postgres (the run record — `RunRepository`) and Redis (the
per-run ephemera — event log, cancel channel, liveness) into the verbs the
router, worker, and reaper call.

Sessions: every verb opens its own short `AsyncSessionLocal()` transaction
rather than riding `get_db` — the service is called from outside any HTTP
request (worker, reaper, Slack, trigger scanner), and even router calls must
commit before the response starts streaming.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    StaleApprovalError,
    StaleRevisionError,
)
from app.model_providers.service import ModelService
from app.redis_client import get_redis
from app.runtime.checkpoints import checkpoint_thread_id
from app.runtime.hitl import (
    build_resume_command,
    is_addressed_resume,
    load_interrupt_scope,
)
from app.runtime.runs import keys
from app.runtime.runs.control import RunControl
from app.runtime.runs.events import RunEventStream, terminal_entry
from app.runtime.runs.liveness import RunLiveness
from app.runtime.runs.models import RunDB
from app.runtime.runs.repository import RunRepository
from app.runtime.runs.settings import run_settings
from app.runtime.runs.state import MultitaskStrategy, RunStatus, is_terminal
from app.sandbox.provider import ensure_sandboxes_available
from app.threads.models import ThreadDB
from app.threads.repository import ThreadRepository


logger = logging.getLogger(__name__)

QUEUE_EDIT_LEASE_SECONDS = 30


def _is_plain_text_input(agent_input: dict) -> bool:
    messages = agent_input.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return False
    message = messages[0]
    return (
        isinstance(message, dict)
        and message.get("type") == "human"
        and isinstance(message.get("content"), str)
    )


class RunService:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()

    async def create(
        self,
        *,
        thread_id: str,
        user_id: str,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        output_schema: dict | None = None,
        delivery: dict | None = None,
        multitask_strategy: MultitaskStrategy = "reject",
        text_only_when_queued: bool = False,
    ) -> RunDB:
        """Create a pending run. Caller has already authorized the thread.

        With the default `reject` strategy, creating a run while the thread has
        a pending/running one raises `DomainValidationError`. With `enqueue`,
        the run simply waits — the dispatcher only claims runs whose thread has
        no running run.

        `delivery` is an opaque push-target descriptor (e.g. Slack channel/
        thread) the worker hands to a delivery consumer; `None` means a pull
        subscriber rides the event log instead.

        This is also the model-availability gate: every launch path (chat
        endpoints, Slack, triggers) funnels through here while still inside
        its initiating context, so ModelUnavailableError surfaces as a 409
        (or a Slack reply / skipped firing) *before* any stream opens or run
        row leaks. Unlike `required_oauth_url`, internal callers are
        deliberately gated too — a run on an unavailable model is invalid no
        matter who enqueues it.
        """
        if input is not None and command is not None:
            raise DomainValidationError("Provide either input or command, not both.")
        # Warm the whitelist cache before taking a pooled connection: on a
        # cold/expired catalog cache the CDN fetch can take seconds, and it
        # must not hold a DB session (pool exhaustion under load).
        await ModelService.list_whitelisted()
        try:
            async with AsyncSessionLocal() as db:
                run = await self.create_in_session(
                    db,
                    thread_id=thread_id,
                    user_id=user_id,
                    input=input,
                    command=command,
                    trigger=trigger,
                    config_overrides=config_overrides,
                    output_schema=output_schema,
                    delivery=delivery,
                    multitask_strategy=multitask_strategy,
                    text_only_when_queued=text_only_when_queued,
                )
                await db.commit()
        except IntegrityError as exc:
            if command is not None:
                raise StaleApprovalError(
                    "This approval request is already being handled."
                ) from exc
            raise
        return run

    async def create_in_session(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        user_id: str,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        output_schema: dict | None = None,
        delivery: dict | None = None,
        multitask_strategy: MultitaskStrategy = "reject",
        text_only_when_queued: bool = False,
        _command_prepared: bool = False,
    ) -> RunDB:
        """Create a pending run in the caller's transaction.

        Request-scoped workflows that create the thread and run together use
        this variant so the dispatcher can never observe an orphaned half.
        The caller owns commit/rollback and should warm the model catalog
        before opening a long-lived transaction.
        """
        if input is not None and command is not None:
            raise DomainValidationError("Provide either input or command, not both.")
        thread = await self._ensure_runnable_thread(db, thread_id)
        if thread.user_id != UUID(user_id):
            raise NotFoundError("Thread not found")
        if command is not None and not _command_prepared:
            command = await self._canonical_command(
                checkpoint_thread_id(thread.workspace_id, thread_id), command
            )
        repository = RunRepository(db)
        if multitask_strategy == "reject":
            await repository.lock_thread_runs(thread_id)
            if await repository.get_active_for_thread(thread_id) is not None:
                raise DomainValidationError("This thread already has an active run.")
        queue_position = None
        if multitask_strategy == "enqueue" and input is not None:
            await repository.lock_thread_runs(thread_id)
            active = await repository.get_active_for_thread(thread_id)
            thread = await db.get(ThreadDB, thread_id)
            if (
                text_only_when_queued
                and (
                    active is not None or (thread is not None and thread.awaiting_input)
                )
                and not _is_plain_text_input(input)
            ):
                raise DomainValidationError(
                    "Only text prompts can be queued while a run is active."
                )
            queue_position = await repository.allocate_queue_position(thread_id)
            if queue_position is None:
                queue_position = await repository.next_queue_position(thread_id)
        return await repository.create(
            RunDB(
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
                user_id=UUID(user_id),
                input=input,
                command=command,
                trigger=trigger,
                config_overrides=config_overrides,
                output_schema=output_schema,
                delivery=delivery,
                multitask_strategy=multitask_strategy,
                queue_position=queue_position,
            )
        )

    @staticmethod
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

    @staticmethod
    async def _ensure_runnable_thread(db: AsyncSession, thread_id: str) -> ThreadDB:
        """The availability gates behind `create`: the thread must exist, its
        pinned model must resolve (whitelist ∧ provider key ∧ admin-enabled),
        else ModelUnavailableError; and every sandbox its agent graph binds
        must answer a probe, else SandboxUnavailableError — a provider outage
        is a 409 here, not a failed run the model gets to reason about."""
        thread = await db.get(ThreadDB, thread_id)
        if thread is None:
            raise NotFoundError("Thread not found")
        await ModelService(db, thread.workspace_id).ensure_available(thread.model_id)
        spec = await AgentRepository(db, thread.workspace_id).get_run_spec(
            thread.agent_id
        )
        if spec is None:
            raise NotFoundError("Agent not found")
        await ensure_sandboxes_available(spec.all_sandbox_rows)
        return thread

    @staticmethod
    async def required_oauth_url(
        db: AsyncSession, agent_id: UUID, user_id: str, workspace_id: UUID
    ) -> str | None:
        """Pre-flight gate: the authorize URL a launch needs first, or None.

        None means every OAuth server the agent **or a subagent** binds is
        connected for this user; a URL means the first one that is not, and the
        caller decides what that means — the HTTP run endpoints answer 401
        {oauth_required, auth_url}, the worker fails a background run fast, and
        `TriggerService.run_now` rejects with an actionable message.

        It used to *raise* the URL and let an app-global handler turn the
        exception into that 401. Returning it keeps the decision at the call
        site, where the three callers already differed (design review §2.4).

        Static — it needs no run state, only the caller's session. Not wired
        into `RunService.create` on purpose: that path is also internal
        (worker, reaper, seeding) and the worker gates itself.

        Fail-open: if probing or OAuth discovery breaks for infra reasons
        (provider down, no metadata), the run launches and the failure surfaces
        in-thread as before — only a confirmed-unauthorized server blocks.
        """
        # Local imports avoid an import cycle (runs.service is imported early by
        # the worker/reaper; AgentService and the MCP connectivity layer pull in
        # far more).
        from app.agents.core.service import AgentService
        from app.mcp.client.connectivity import initiate_oauth, probe_authorization
        from app.mcp.client.exceptions import OAuthAuthorizationRequired
        from app.mcp.servers.models import MCPAuthType
        from app.mcp.servers.repository import MCPServerRepository

        bindings = await AgentService(db, workspace_id).collect_run_bindings(agent_id)
        if not bindings:
            return None

        # Auth is per (user, server), so dedupe server ids — a server shared by
        # the agent and a subagent need only be probed once.
        server_ids = {b.mcp_server_id for b in bindings}
        rows = await MCPServerRepository(db, workspace_id).list_by_ids(server_ids)
        servers = [s for s in rows if s.auth_type == MCPAuthType.oauth2]
        # DB reads done — release the pooled connection before the probes'
        # network IO (token refresh, OAuth metadata discovery can take
        # seconds). expire_on_commit=False keeps the loaded rows usable.
        await db.commit()

        # Concurrent, fail-open and memoized — shared with the readiness
        # endpoint, which used to carry a sequential fail-loud copy (§4.1).
        authorized = await probe_authorization(servers, user_id, workspace_id)
        for server in servers:
            if authorized.get(server.id, True):
                continue
            try:
                # Ends in OAuthAuthorizationRequired(auth_url) for the first
                # unauthorized server; the caller connects it and retries.
                await initiate_oauth(server, user_id, workspace_id, db)
            except OAuthAuthorizationRequired as exc:
                return exc.url
            except Exception:  # noqa: BLE001 — fail-open: a probe error must not block the run
                logger.warning(
                    "OAuth pre-flight for MCP server %s failed; letting the run launch",
                    server.id,
                    exc_info=True,
                )
        return None

    async def get(self, run_id: str, workspace_id: UUID | None = None) -> RunDB:
        async with AsyncSessionLocal() as db:
            record = await RunRepository(db, workspace_id).get(run_id)
        if record is None:
            raise NotFoundError("Run not found")
        return record

    async def list_for_thread(self, thread_id: str, workspace_id: UUID) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db, workspace_id).list_for_thread(thread_id)

    async def next_for_thread(
        self, thread_id: str, workspace_id: UUID, after: RunDB | None = None
    ) -> RunDB | None:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db, workspace_id).next_for_thread(
                thread_id, after
            )

    async def get_active(self, thread_id: str, workspace_id: UUID) -> RunDB | None:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db, workspace_id).get_active_for_thread(
                thread_id
            )

    async def list_queued_prompts(
        self, thread_id: str, workspace_id: UUID
    ) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db, workspace_id).list_queued_prompts(thread_id)

    async def begin_queue_edit(
        self, thread_id: str, run_id: str, workspace_id: UUID
    ) -> None:
        async with AsyncSessionLocal() as db:
            records = await RunRepository(db, workspace_id).list_queued_prompts(
                thread_id, for_update=True
            )
            if run_id not in {record.id for record in records}:
                raise StaleRevisionError(
                    "This prompt has already started and can no longer be edited."
                )
            expires_at = datetime.now(UTC) + timedelta(seconds=QUEUE_EDIT_LEASE_SECONDS)
            await ThreadRepository(db, workspace_id).set_queue_edit_lease(
                thread_id, run_id, expires_at
            )
            await db.commit()

    async def end_queue_edit(
        self, thread_id: str, run_id: str, workspace_id: UUID
    ) -> None:
        async with AsyncSessionLocal() as db:
            await ThreadRepository(db, workspace_id).clear_queue_edit_lease(
                thread_id, run_id
            )
            await db.commit()

    async def update_queued_prompt(
        self, run_id: str, run_input: dict, workspace_id: UUID
    ) -> RunDB:
        async with AsyncSessionLocal() as db:
            record = await RunRepository(db, workspace_id).update_queued_prompt(
                run_id, run_input
            )
            if record is None:
                raise StaleRevisionError(
                    "This prompt has already started and can no longer be edited."
                )
            await ThreadRepository(db, workspace_id).clear_queue_edit_lease(
                record.thread_id, run_id
            )
            await db.commit()
        return record

    async def reorder_queued_prompts(
        self, thread_id: str, ordered_ids: list[str], workspace_id: UUID
    ) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            repository = RunRepository(db, workspace_id)
            await repository.lock_thread_runs(thread_id)
            records = await repository.list_queued_prompts(thread_id, for_update=True)
            current_ids = {record.id for record in records}
            if (
                len(ordered_ids) != len(current_ids)
                or len(set(ordered_ids)) != len(ordered_ids)
                or set(ordered_ids) != current_ids
            ):
                raise StaleRevisionError(
                    "The prompt queue changed. Reload it before reordering."
                )
            await repository.set_queue_positions(records, ordered_ids)
            await db.commit()
            return await repository.list_queued_prompts(thread_id)

    async def remove_queued_prompt(self, run_id: str) -> None:
        record = await self.get(run_id)
        if (
            record.status != RunStatus.pending
            or record.queue_position is None
            or record.input is None
        ):
            raise StaleRevisionError(
                "This prompt has already started and can no longer be removed."
            )
        updated = await self.finalize(
            run_id, RunStatus.cancelled, expected=RunStatus.pending
        )
        if updated is None or updated.status != RunStatus.cancelled:
            raise StaleRevisionError(
                "This prompt has already started and can no longer be removed."
            )
        await self.end_queue_edit(record.thread_id, run_id, record.workspace_id)

    async def list_active_for_user(
        self, user_id: str, workspace_id: UUID, *, recent_seconds: int = 0
    ) -> list[RunDB]:
        """The user's pending/running runs — backs the sidebar activity poll.

        `recent_seconds > 0` also returns runs that finished within that
        window, so the poller can react to terminal outcomes (error badge,
        run history) without refetching threads.
        """
        finished_after = (
            datetime.now(UTC) - timedelta(seconds=recent_seconds)
            if recent_seconds > 0
            else None
        )
        async with AsyncSessionLocal() as db:
            return await RunRepository(db, workspace_id).list_active_for_user(
                UUID(user_id), finished_after=finished_after
            )

    async def claim_next(self) -> RunDB | None:
        """Atomically claim the next dispatchable run (the dispatcher's poll).
        Claiming *is* the pending → running transition."""
        async with AsyncSessionLocal() as db:
            run = await RunRepository(db).claim_next()
            await db.commit()
        return run

    async def cancel(self, run_id: str) -> RunDB:
        """Stop a run. A pending run is finalized directly; a running one gets
        a signal its worker picks up. Terminal runs are a no-op."""
        record = await self.get(run_id)
        if is_terminal(record.status):
            return record
        if record.status == RunStatus.pending:
            updated = await self.finalize(
                run_id, RunStatus.cancelled, expected=RunStatus.pending
            )
            if updated is not None and updated.status == RunStatus.cancelled:
                return updated
            # A dispatcher claimed it between our read and the guarded update —
            # fall through and cancel it like any running run.
        await RunControl(
            run_id, self.redis, workspace_id=record.workspace_id
        ).request_cancel(ttl=run_settings.ttl_seconds)
        return record

    async def stream(
        self, run_id: str, last_event_id: str = "0", *, block_ms: int = 15000
    ) -> AsyncGenerator[str, None]:
        """Relay a run's stored events (raw log entries) from `last_event_id`
        until the terminal entry.

        The Postgres record backstops the Redis log twice over: a terminal run
        whose log has expired (reattach later than the TTL) yields a synthetic
        terminal immediately, and an idle block window on a terminal run
        (worker died between the DB commit and publishing the terminal) does
        the same instead of waiting forever on a stream that will never end.
        """
        record = await self.get(run_id)
        events = RunEventStream(run_id, self.redis, workspace_id=record.workspace_id)
        if not await events.exists() and is_terminal(record.status):
            yield terminal_entry(record.status, record.error)
            return
        cursor = last_event_id or "0"
        while True:
            batch = await events.read_batch(cursor, block_ms=block_ms)
            if batch is None:
                record = await self.get(run_id)
                if is_terminal(record.status):
                    yield terminal_entry(record.status, record.error)
                    return
                continue
            cursor, chunks, ended = batch
            for sse in chunks:
                yield sse
            if ended:
                return

    async def wait_for_terminal(self, run_id: str) -> RunDB:
        """Block until the run reaches a terminal state, then return its record.

        The synchronous `/runs/invoke` consumer: it rides the event log's
        blocking read (no polling) and discards the chunks — it only needs to
        know the run finished, then reads the result back from the checkpoint."""
        async for _ in self.stream(run_id):
            pass  # drain to the terminal entry
        return await self.get(run_id)

    async def finalize(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        expected: RunStatus | None = None,
    ) -> RunDB | None:
        """Move a run to a terminal state.

        One Postgres transaction covers the run's terminal update *and* the
        `threads.last_run_status` stamp, so they can never disagree. Then the
        terminal lifecycle event is published and the Redis ephemera get
        their TTL.
        Idempotent — a run that's already terminal is left untouched (worker
        and reaper may both call this). Returns the current record, or `None`
        if the run doesn't exist.
        """
        async with AsyncSessionLocal() as db:
            repository = RunRepository(db)
            before = await repository.get(run_id)
            was_pending_queue = (
                before is not None
                and before.status == RunStatus.pending
                and before.queue_position is not None
            )
            was_command = before is not None and before.command is not None
            thread_id = await repository.finalize_run(
                run_id, status, error=error, expected=expected
            )
            if thread_id is not None:
                threads = ThreadRepository(
                    db, before.workspace_id if before is not None else None
                )
                # Removing a prompt that never ran is queue maintenance, not
                # the outcome of the conversation's latest turn.
                cancelled_waiter = was_pending_queue and status == RunStatus.cancelled
                if not cancelled_waiter:
                    await threads.set_last_run_status(thread_id, status)
                if status == RunStatus.interrupted:
                    await threads.set_awaiting_input(thread_id, True)
                elif was_command and status == RunStatus.success:
                    await threads.set_awaiting_input(thread_id, False)
            await db.commit()
            record = await repository.get(run_id)
        if thread_id is not None:
            await RunEventStream(
                run_id, self.redis, workspace_id=record.workspace_id
            ).publish_end(status, error)
        # `thread_id is None` means the guarded UPDATE matched nothing, which
        # covers three different situations and only two of them are finished:
        #   1. the run was already terminal — expire, it is over;
        #   2. its row is gone (the thread was deleted mid-run and CASCADEd) —
        #      expire, or the ephemera keep no TTL at all and sit in Redis for
        #      ever, with no second chance because nothing will finalize it again;
        #   3. it moved out of `expected` and is **still running** — a pending
        #      cancel or a reaper sweep losing a race with a dispatcher claim.
        # Expiring in case 3 would clear a live run's liveness key and hand the
        # reaper a false "dead worker", which is precisely the failure the
        # two-sample rule exists to prevent.
        if thread_id is not None or record is None or is_terminal(record.status):
            await self._expire_ephemera(
                run_id, record.workspace_id if record is not None else None
            )
        return record

    # --- reaper support -----------------------------------------------------

    async def list_running(self) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_running()

    async def list_stuck_pending(self, older_than: datetime) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_stuck_pending(older_than)

    async def prune_terminal(self, older_than: datetime) -> int:
        async with AsyncSessionLocal() as db:
            count = await RunRepository(db).prune_terminal(older_than)
            await db.commit()
        return count

    async def _expire_ephemera(self, run_id: str, workspace_id: UUID | None) -> None:
        """TTL the finished run's event log + control key (the reattach/replay
        window) and drop its liveness key immediately."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.expire(
                keys.run_events_key(run_id, workspace_id), run_settings.ttl_seconds
            )
            pipe.expire(
                keys.run_control_key(run_id, workspace_id), run_settings.ttl_seconds
            )
            await pipe.execute()
        await RunLiveness(run_id, self.redis, workspace_id=workspace_id).clear()
