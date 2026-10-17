"""Redis coordination only. Credentials and executable tools stay in the worker.

Request-only instances enqueue work; the run owner consumes it using its live
MCP sessions. A short lease fails closed if the worker dies. Operation IDs make
HTTP retries idempotent; uncertain tool outcomes are never automatically replayed.

A call that needs the user (approval, OAuth reconnect) is one *pending decision*
of the run, surfaced exactly like a graph interrupt: the worker publishes an
`input.requested` event under `BRIDGE_NAMESPACE`, `/state` lists it while it
pends (`list_pending`), and `input.respond` answers it (`decide`). Only the
decision store differs from the checkpoint-backed HITL — the sandbox script is
blocked inside a running tool, so there is no graph to pause.
"""

import json
from typing import Any

from app.exceptions import (
    AlreadyExistsError,
    CallLimitError,
    DomainValidationError,
    LeaseEndedError,
    NotFoundError,
    OperationExpiredError,
    PayloadTooLargeError,
    PermissionDeniedError,
    StaleApprovalError,
    StaleRevisionError,
)
from app.redis_client import get_redis
from app.runtime.sandbox_mcp import keys
from app.runtime.sandbox_mcp.schemas import CallRequest
from app.runtime.sandbox_mcp.settings import bridge_settings


#: Protocol namespace of a bridge request. One segment deep so the client's
#: root subscription (prefix `[]`, depth 1) receives it; distinct from the
#: root so it never reads as the graph itself pausing.
BRIDGE_NAMESPACE = ["sandbox-mcp"]

_WAITING = ("approval_required", "oauth_required")
_DECISIONS = {"approval_required": {"approve", "reject"}, "oauth_required": {"reject"}}


_ENQUEUE = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -3 end
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
if redis.call('SISMEMBER', KEYS[3], ARGV[1]) == 1 then return -2 end
if redis.call('SCARD', KEYS[3]) >= tonumber(ARGV[4]) then return -1 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('SADD', KEYS[3], ARGV[1])
redis.call('EXPIRE', KEYS[3], ARGV[3])
redis.call('RPUSH', KEYS[4], ARGV[1])
redis.call('EXPIRE', KEYS[4], ARGV[3])
return 1
"""


# Compare raw JSON rather than round-tripping it through Lua's cjson: empty
# arrays in tool arguments must remain arrays. Missing records are never recreated.
_UPDATE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'XX', 'EX', ARGV[3])
return 1
"""

_DECIDE = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
if redis.call('GET', KEYS[3]) ~= ARGV[1] then return 0 end
local raw = redis.call('GET', KEYS[2])
if not raw then return 0 end
local operation = cjson.decode(raw)
if operation.phase ~= ARGV[2] or operation.status ~= ARGV[3] then return 0 end
if redis.call('SET', KEYS[4], ARGV[4], 'NX', 'EX', ARGV[5]) then return 1 end
return 0
"""


def request_payload(operation: dict, agent: str) -> dict:
    """The `input.requested` payload for a waiting operation — the same shape
    live (worker) and on hydration (`list_pending`). `action_requests` is the
    HITL vocabulary every consumer already reads; `sandbox_mcp` is what the
    bridge card needs to answer it."""
    return {
        "action_requests": [
            {"name": operation["tool"], "args": operation["arguments"]}
        ],
        "sandbox_mcp": {
            "operation_id": operation["id"],
            "agent": agent,
            "status": operation["status"],
            "auth_url": operation.get("auth_url"),
        },
    }


class SandboxMcpService:
    def __init__(self, redis=None):
        self.redis = redis if redis is not None else get_redis()

    async def get_lease(self, scope: str) -> dict:
        raw = await self.redis.get(keys.lease_key(scope))
        if raw is None:
            raise LeaseEndedError("Sandbox MCP session ended")
        return json.loads(raw)

    async def create(self, scope: str, call: CallRequest) -> dict:
        lease = await self.get_lease(scope)
        if call.tool not in lease["tools"]:
            raise PermissionDeniedError(
                "Tool is disabled or unavailable for this agent"
            )
        payload = call.model_dump_json()
        if len(payload.encode()) > bridge_settings.max_request_bytes:
            raise PayloadTooLargeError("MCP arguments exceed the request limit")
        # Create the record and enqueue atomically. A separate, lease-renewed
        # seen set prevents an expired result record from replaying a write.
        created = await self.redis.eval(
            _ENQUEUE,
            4,
            keys.lease_key(scope),
            keys.operation_key(scope, str(call.id)),
            keys.seen_key(scope),
            keys.queue_key(scope),
            str(call.id),
            json.dumps({"status": "queued", **json.loads(payload)}),
            bridge_settings.operation_seconds,
            bridge_settings.max_calls,
        )
        if created == -1:
            raise CallLimitError("Run MCP call limit reached")
        if created == -2:
            raise AlreadyExistsError(
                "Operation result expired; check its outcome before retrying"
            )
        if created == -3:
            raise LeaseEndedError("Sandbox MCP session ended")
        stored = await self.get(scope, str(call.id))
        if stored["tool"] != call.tool or stored["arguments"] != call.arguments:
            raise AlreadyExistsError("Operation ID already used for another call")
        return {"id": str(call.id), "status": stored["status"]}

    async def get(self, scope: str, operation_id: str) -> dict:
        await self.get_lease(scope)
        raw = await self.redis.get(keys.operation_key(scope, operation_id))
        if raw is None:
            raise OperationExpiredError("MCP operation not found")
        await self.redis.expire(
            keys.operation_key(scope, operation_id), bridge_settings.operation_seconds
        )
        return json.loads(raw)

    async def update(self, scope: str, operation_id: str, updates: dict) -> dict:
        """Merge `updates` into the record and return it. CAS prevents expiry
        between GET and SET from resurrecting a partial operation; a retry
        only updates metadata, never dispatches a tool."""
        operation_key = keys.operation_key(scope, operation_id)
        for _ in range(3):
            raw = await self.redis.get(operation_key)
            if raw is None:
                raise OperationExpiredError("MCP operation expired")
            merged = {**json.loads(raw), **updates}
            if await self.redis.eval(
                _UPDATE,
                1,
                operation_key,
                raw,
                json.dumps(merged),
                bridge_settings.operation_seconds,
            ):
                return merged
        raise StaleRevisionError("MCP operation changed during update")

    # --- pending decisions ----------------------------------------------------

    async def mark_pending(
        self, scope: str, operation_id: str, interrupt_id: str
    ) -> None:
        """Record that `operation_id` waits on the user under `interrupt_id`."""
        ttl = bridge_settings.operation_seconds
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(keys.pending_key(scope), operation_id, ex=ttl)
            pipe.set(
                keys.interrupt_key(interrupt_id),
                json.dumps({"scope": scope, "operation_id": operation_id}),
                ex=ttl,
            )
            await pipe.execute()

    async def clear_pending(self, scope: str, interrupt_id: str) -> None:
        await self.redis.delete(
            keys.pending_key(scope), keys.interrupt_key(interrupt_id)
        )

    async def list_pending(self, thread_id: str, user_id: str) -> list[dict]:
        """The thread's waiting bridge requests as protocol interrupts
        (`{id, value, namespace}`) — what `/state` hydration lists so a
        reloaded page accepts the replayed `input.requested`. Only the run's
        owner sees them: an admin reading the thread gets neither the tool
        arguments nor the OAuth URL, and could not answer anyway."""
        found: list[dict] = []
        for scope in await self.redis.smembers(keys.thread_index_key(thread_id)):
            try:
                lease = await self.get_lease(scope)
                if lease["user_id"] != user_id:
                    continue
                operation_id = await self.redis.get(keys.pending_key(scope))
                if not operation_id:
                    continue
                operation = await self.get(scope, operation_id)
            except (LeaseEndedError, OperationExpiredError):
                continue
            if operation["status"] in _WAITING:
                found.append(
                    {
                        "id": operation["phase"],
                        "value": request_payload(operation, lease["agent"]),
                        "namespace": BRIDGE_NAMESPACE,
                    }
                )
        return found

    async def decide(
        self, thread_id: str, user_id: str, interrupt_id: str, decision: Any
    ) -> bool:
        """Answer a bridge request. False when `interrupt_id` is not one (the
        caller resumes the graph instead); raises when it is but cannot be
        answered — `StaleApprovalError` once it is no longer waiting."""
        raw = await self.redis.get(keys.interrupt_key(interrupt_id))
        if raw is None:
            return False
        target = json.loads(raw)
        scope, operation_id = target["scope"], target["operation_id"]
        lease = await self.get_lease(scope)
        if lease["thread_id"] != thread_id or lease["user_id"] != user_id:
            raise NotFoundError("MCP operation not found")
        operation = await self.get(scope, operation_id)
        if operation.get("phase") != interrupt_id:
            raise StaleApprovalError("This request was already handled.")
        if not isinstance(decision, str) or decision not in _DECISIONS.get(
            operation["status"], set()
        ):
            raise DomainValidationError(
                f"Decision {decision!r} does not apply to this request."
            )
        accepted = await self.redis.eval(
            _DECIDE,
            4,
            keys.lease_key(scope),
            keys.operation_key(scope, operation_id),
            keys.pending_key(scope),
            keys.decision_key(scope, operation_id, interrupt_id),
            operation_id,
            interrupt_id,
            operation["status"],
            decision,
            bridge_settings.operation_seconds,
        )
        if not accepted:
            raise StaleApprovalError(
                "This request is no longer pending or was already answered."
            )
        return True
