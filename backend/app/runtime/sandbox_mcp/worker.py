"""One bridge scope per sandbox-enabled agent, owned by the running worker."""

import asyncio
import json
import logging
import secrets
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.database import AsyncSessionLocal
from app.mcp.client.exceptions import as_oauth_required
from app.mcp.client.oauth_events import OAuthCompletion
from app.mcp.client.tools import preserve_mcp_result
from app.runtime.sandbox_mcp.service import SandboxMcpService, key, scope_of
from app.runtime.sandbox_mcp.settings import bridge_settings
from app.runtime.toolset import Toolset


logger = logging.getLogger(__name__)


SDK_ROOT = "/tmp/auxilia-mcp-sdk"  # nosec B108 - sandbox-local, contains no credentials
SDK_SOURCE = Path(__file__).with_name("client.py")


class BridgeSession:
    def __init__(
        self, resolved, thread, backend, broker: SandboxMcpService | None = None
    ):
        self.backend = backend
        self.resolved = resolved
        self.thread = thread
        self.broker = broker or SandboxMcpService()
        self.token = secrets.token_urlsafe(32)
        self.scope = scope_of(self.token)
        self._tasks: list[asyncio.Task] = []
        self._closed = False
        self._stack = AsyncExitStack()
        self.tools = {t.tool.name: t for t in resolved.live.tools}

    async def __aenter__(self):
        await self._lease()
        index = f"sandbox-mcp:thread:{self.thread.id}"
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
                key(self.scope, "lease"), key(self.scope, "queue")
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
                f"sandbox-mcp:thread:{self.thread.id}", self.scope
            )
        except RedisError:
            logger.warning(
                "Cannot remove sandbox MCP index; it will expire", exc_info=True
            )

    async def _lease(self, *, renew: bool = False):
        metadata = {
            "thread_id": self.thread.id,
            "user_id": str(self.thread.user_id),
            "agent": self.resolved.config.name,
            "tools": {
                name: {
                    "description": t.tool.description,
                    "input_schema": t.tool.get_input_schema().model_json_schema(),
                    "requires_approval": t.requires_approval,
                }
                for name, t in self.tools.items()
            },
        }
        await self.broker.redis.expire(
            key(self.scope, "seen"), bridge_settings.operation_seconds
        )
        await self.broker.redis.expire(
            f"sandbox-mcp:thread:{self.thread.id}", bridge_settings.operation_seconds
        )
        stored = await self.broker.redis.set(
            key(self.scope, "lease"),
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
                    key(self.scope, "queue"), timeout=1
                )
                if item:
                    await self._execute(item[1])
        except Exception:
            logger.exception("Sandbox MCP consumer failed")
            raise
        finally:
            self._tasks[0].cancel()
            await self.broker.redis.delete(key(self.scope, "lease"))

    async def _decision(self, operation_id: str, status: str, **fields) -> str:
        phase = str(uuid4())
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
        await self.broker.write(
            self.scope, operation_id, {"status": status, "phase": phase, **fields}
        )
        await self.broker.redis.set(
            key(self.scope, "pending"),
            operation_id,
            ex=bridge_settings.operation_seconds,
        )
        try:
            async with asyncio.timeout(bridge_settings.operation_seconds):
                while True:
                    value = await self.broker.redis.get(
                        key(self.scope, f"decision:{operation_id}:{phase}")
                    )
                    if value:
                        return value
                    if completion is not None and await completion.completed():
                        return "reconnect"
                    await asyncio.sleep(0.5)
        finally:
            await self.broker.redis.delete(key(self.scope, "pending"))

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
        live = await self._stack.enter_async_context(Toolset.open(prepared))
        self.tools = {t.tool.name: t for t in live.tools}

    async def _execute(self, operation_id: str):
        try:
            await self._run_operation(operation_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            logger.info("Dropping expired sandbox MCP operation %s", operation_id)

    async def _run_operation(self, operation_id: str):
        operation = await self.broker.read(self.scope, operation_id)
        name, arguments = operation["tool"], operation["arguments"]
        try:
            tool = self.tools.get(name)
            if tool is None:
                raise PermissionError("Tool is disabled or unavailable for this agent")
            if tool.requires_approval:
                decision = await self._decision(operation_id, "approval_required")
                if decision != "approve":
                    raise PermissionError("User rejected this tool call")
            await self.broker.write(self.scope, operation_id, {"status": "running"})
            token = preserve_mcp_result.set(True)
            try:
                # Only a positively identified OAuth challenge is retried. Network
                # timeouts and uncertain writes become errors, never retries.
                reconnect = False
                for attempt in range(3):
                    try:
                        if reconnect:
                            await self._reconnect()
                        current = self.tools.get(name)
                        if current is None:
                            raise PermissionError("Tool is no longer available")
                        await self.broker.write(
                            self.scope,
                            operation_id,
                            {"status": "running", "auth_url": None},
                        )
                        message = await asyncio.wait_for(
                            current.tool.ainvoke(
                                {
                                    "type": "tool_call",
                                    "id": operation_id,
                                    "name": name,
                                    "args": arguments,
                                }
                            ),
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
                            raise PermissionError(
                                "User cancelled authorization"
                            ) from None
                        reconnect = True
                artifact = (
                    message.artifact if isinstance(message.artifact, dict) else {}
                )
                result: dict[str, Any] = {
                    "content": message.content,
                    "structured_content": artifact.get(
                        "structured_content", artifact.get("structuredContent")
                    ),
                    "is_error": message.status == "error",
                }
                payload = json.dumps(result, ensure_ascii=False).encode()
                if len(payload) > bridge_settings.max_result_bytes:
                    raise ValueError(
                        "MCP completed but its result exceeds the bridge limit; check the outcome before repeating a write"
                    )
                folder = f"/tmp/auxilia-mcp-results/{self.scope}"
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
                await self.broker.write(
                    self.scope,
                    operation_id,
                    {"status": "complete", "path": path, "auth_url": None},
                )
            finally:
                preserve_mcp_result.reset(token)
        except HTTPException:
            raise  # Missing/expired records are handled without recreating them.
        except Exception as exc:  # noqa: BLE001 - return operation failures to sandbox code
            await self.broker.write(
                self.scope,
                operation_id,
                {
                    "status": "error",
                    "error": str(exc) or type(exc).__name__,
                    "auth_url": None,
                },
            )
