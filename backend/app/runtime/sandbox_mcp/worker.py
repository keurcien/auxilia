"""One bridge scope per sandbox-enabled agent, owned by the running worker."""

import asyncio
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from app.database import AsyncSessionLocal
from app.exceptions import OperationExpiredError
from app.mcp.client.exceptions import as_oauth_required
from app.mcp.client.oauth_events import OAuthCompletion
from app.runtime.protocol import events as ev
from app.runtime.sandbox_mcp import keys
from app.runtime.sandbox_mcp.service import (
    BRIDGE_NAMESPACE,
    SandboxMcpService,
    request_payload,
)
from app.runtime.sandbox_mcp.settings import bridge_settings
from app.runtime.toolset import AgentTool, Toolset


logger = logging.getLogger(__name__)


SDK_ROOT = "/tmp/auxilia-mcp-sdk"  # nosec B108 - sandbox-local, contains no credentials
SDK_SOURCE = Path(__file__).with_name("client.py")
#: Where results land *inside the sandbox* (one folder per capability scope).
#: A path on the sandbox's disk, not this process's — no temp-file race here.
RESULTS_ROOT = "/tmp/auxilia-mcp-results"  # nosec B108

#: Where the bridge hands a protocol event to the run's event log. `None`
#: (tests, callers without a log) leaves requests reachable through `/state`
#: hydration only.
EventSink = Callable[[dict], Awaitable[Any]]


async def _drop_event(_event: dict) -> None:
    return None


class BridgeSession:
    def __init__(
        self,
        resolved,
        thread,
        backend,
        broker: SandboxMcpService | None = None,
        publish: EventSink | None = None,
    ):
        self.backend = backend
        self.resolved = resolved
        self.thread = thread
        self.broker = broker or SandboxMcpService()
        self.publish = publish or _drop_event
        self.token = secrets.token_urlsafe(32)
        self.scope = keys.scope_of(self.token)
        self._tasks: list[asyncio.Task] = []
        self._closed = False
        self._stack = AsyncExitStack()
        self.live: Toolset = resolved.live

    async def __aenter__(self):
        await self._lease()
        index = keys.thread_index_key(self.thread.id)
        await self.broker.redis.sadd(index, self.scope)
        await self.broker.redis.expire(index, bridge_settings.operation_seconds)
        self._tasks = [
            asyncio.create_task(self._heartbeat()),
            asyncio.create_task(self._consume()),
        ]
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Stop accepting work before teardown or sandbox snapshotting begins.
        try:
            await self.broker.redis.delete(
                keys.lease_key(self.scope), keys.queue_key(self.scope)
            )
        except RedisError:
            logger.warning(
                "Cannot revoke sandbox MCP lease; it will expire", exc_info=True
            )
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await self._stack.aclose()
        try:
            await self.broker.redis.srem(
                keys.thread_index_key(self.thread.id), self.scope
            )
        except RedisError:
            logger.warning(
                "Cannot remove sandbox MCP index; it will expire", exc_info=True
            )

    def _tool(self, name: str) -> AgentTool | None:
        return next((t for t in self.live.tools if t.tool.name == name), None)

    async def _lease(self, *, renew: bool = False):
        metadata = {
            "thread_id": self.thread.id,
            "user_id": str(self.thread.user_id),
            "agent": self.resolved.config.name,
            "tools": {
                t.tool.name: {
                    "description": t.tool.description,
                    # langchain types the schema as a pydantic v1|v2 union;
                    # `langchain.mcp` only ever builds v2 models.
                    "input_schema": t.tool.get_input_schema().model_json_schema(),  # type: ignore[union-attr]
                    "requires_approval": t.requires_approval,
                }
                for t in self.live.tools
            },
        }
        await self.broker.redis.expire(
            keys.seen_key(self.scope), bridge_settings.operation_seconds
        )
        await self.broker.redis.expire(
            keys.thread_index_key(self.thread.id), bridge_settings.operation_seconds
        )
        stored = await self.broker.redis.set(
            keys.lease_key(self.scope),
            json.dumps(metadata),
            ex=bridge_settings.lease_seconds,
            xx=renew,
            nx=not renew,
        )
        if not stored:
            raise RuntimeError("Sandbox MCP lease expired; start a new run")

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(bridge_settings.lease_seconds / 3)
                await self._lease(renew=True)
        except Exception:
            # Fail closed; never let an orphaned consumer continue calling MCP.
            self._tasks[1].cancel()
            logger.exception("Sandbox MCP lease renewal failed")
            raise

    async def _consume(self):
        try:
            while True:
                item = await self.broker.redis.blpop(
                    keys.queue_key(self.scope), timeout=1
                )
                if item:
                    await self._execute(item[1])
        except Exception:
            logger.exception("Sandbox MCP consumer failed")
            raise
        finally:
            self._tasks[0].cancel()
            await self.broker.redis.delete(keys.lease_key(self.scope))

    async def _decision(self, operation_id: str, status: str, **fields) -> str:
        """Park the operation on the user and wait for their answer.

        The wait is one protocol interrupt: published to the run's event log
        as `input.requested` (the chat renders it like any approval) and
        answered through `input.respond` → `SandboxMcpService.decide`. An
        OAuth wait also ends on its own once the callback stores the token.
        """
        interrupt_id = uuid4().hex
        completion = (
            await OAuthCompletion.for_challenge(
                fields.get("auth_url", ""),
                user_id=str(self.thread.user_id),
                server_ids={
                    str(binding.mcp_server_id)
                    for binding in self.resolved.config.mcp_servers
                },
                redis=self.broker.redis,
            )
            if status == "oauth_required"
            else None
        )
        operation = await self.broker.update(
            self.scope,
            operation_id,
            {"status": status, "phase": interrupt_id, **fields},
        )
        await self.broker.mark_pending(self.scope, operation_id, interrupt_id)
        try:
            await self.publish(
                ev.input_requested(
                    BRIDGE_NAMESPACE,
                    interrupt_id=interrupt_id,
                    payload=request_payload(operation, self.resolved.config.name),
                )
            )
            decision = keys.decision_key(self.scope, operation_id, interrupt_id)
            async with asyncio.timeout(bridge_settings.operation_seconds):
                while True:
                    value = await self.broker.redis.get(decision)
                    if value:
                        return value
                    if completion is not None and await completion.completed():
                        return "reconnect"
                    await asyncio.sleep(0.5)
        finally:
            await self.broker.clear_pending(self.scope, interrupt_id)

    async def _reconnect(self):
        # Close our previous replacement before opening another. The initial
        # live toolset is shared with direct calls and remains owned by Agent's
        # outer ExitStack; only replacement sessions belong to this stack.
        await self._stack.aclose()
        self._stack = AsyncExitStack()
        async with AsyncSessionLocal() as db:
            prepared = await Toolset.prepare(
                self.resolved.config.mcp_servers,
                db,
                str(self.thread.user_id),
                apply_ui=False,
            )
        self.live = await self._stack.enter_async_context(Toolset.open(prepared))

    async def _execute(self, operation_id: str):
        try:
            await self._run_operation(operation_id)
        except OperationExpiredError:
            logger.info("Dropping expired sandbox MCP operation %s", operation_id)

    async def _run_operation(self, operation_id: str):
        operation = await self.broker.get(self.scope, operation_id)
        name, arguments = operation["tool"], operation["arguments"]
        try:
            tool = self._tool(name)
            if tool is None:
                raise PermissionError("Tool is disabled or unavailable for this agent")
            if tool.requires_approval:
                decision = await self._decision(operation_id, "approval_required")
                if decision != "approve":
                    raise PermissionError("User rejected this tool call")
            # Only a positively identified OAuth challenge is retried. Network
            # timeouts and uncertain writes become errors, never retries.
            reconnect = False
            for attempt in range(3):
                try:
                    if reconnect:
                        await self._reconnect()
                    if self._tool(name) is None:
                        raise PermissionError("Tool is no longer available")
                    await self.broker.update(
                        self.scope,
                        operation_id,
                        {"status": "running", "auth_url": None},
                    )
                    outcome = await asyncio.wait_for(
                        self.live.call_raw(name, arguments, call_id=operation_id),
                        timeout=bridge_settings.operation_seconds,
                    )
                    break
                except Exception as exc:
                    oauth = as_oauth_required(exc)
                    if oauth is None or attempt == 2:
                        raise
                    decision = await self._decision(
                        operation_id, "oauth_required", auth_url=oauth.url
                    )
                    if decision != "reconnect":
                        raise PermissionError("User cancelled authorization") from None
                    reconnect = True
            result: dict[str, Any] = {
                "content": outcome.content,
                "structured_content": outcome.structured_content,
                "is_error": outcome.is_error,
            }
            payload = json.dumps(result, ensure_ascii=False).encode()
            if len(payload) > bridge_settings.max_result_bytes:
                raise ValueError(
                    "MCP completed but its result exceeds the bridge limit; check the outcome before repeating a write"
                )
            folder = f"{RESULTS_ROOT}/{self.scope}"
            created = await asyncio.to_thread(
                self.backend.execute, f"mkdir -p {folder}"
            )
            if created.exit_code != 0:
                raise RuntimeError(
                    "MCP completed but its result could not be saved; check the outcome before retrying"
                )
            path = f"{folder}/{operation_id}.json"
            uploaded = await asyncio.to_thread(
                self.backend.upload_files, [(path, payload)]
            )
            if len(uploaded) != 1 or uploaded[0].error:
                raise RuntimeError(
                    "MCP ran but its result could not be saved; check the outcome before retrying"
                )
            await self.broker.update(
                self.scope,
                operation_id,
                {"status": "complete", "path": path, "auth_url": None},
            )
        except OperationExpiredError:
            raise  # Missing/expired records are handled without recreating them.
        except Exception as exc:  # noqa: BLE001 - return operation failures to sandbox code
            # `str()` of an exhausted OAuth challenge is the bare authorize
            # URL; the sandbox (and so the model) never gets credentials material.
            if as_oauth_required(exc) is not None:
                error = "MCP authorization required; reconnect the server in chat"
            else:
                error = str(exc) or type(exc).__name__
            await self.broker.update(
                self.scope,
                operation_id,
                {"status": "error", "error": error, "auth_url": None},
            )
