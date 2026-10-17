"""Redis coordination only. Credentials and executable tools stay in the worker.

Request-only instances enqueue work; the run owner consumes it using its live
MCP sessions. A short lease fails closed if the worker dies. Operation IDs make
HTTP retries idempotent; uncertain tool outcomes are never automatically replayed.
"""

import hashlib
import json

from fastapi import HTTPException

from app.redis_client import get_redis
from app.runtime.sandbox_mcp.schemas import CallRequest
from app.runtime.sandbox_mcp.settings import bridge_settings


def scope_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def key(scope: str, suffix: str) -> str:
    return f"sandbox-mcp:{scope}:{suffix}"


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


class SandboxMcpService:
    def __init__(self, redis=None):
        self.redis = redis if redis is not None else get_redis()

    async def active(self, scope: str) -> dict:
        raw = await self.redis.get(key(scope, "lease"))
        if raw is None:
            raise HTTPException(410, "Sandbox MCP session ended")
        return json.loads(raw)

    async def enqueue(self, scope: str, call: CallRequest) -> dict:
        lease = await self.active(scope)
        if call.tool not in lease["tools"]:
            raise HTTPException(403, "Tool is disabled or unavailable for this agent")
        payload = call.model_dump_json()
        if len(payload.encode()) > bridge_settings.max_request_bytes:
            raise HTTPException(413, "MCP arguments exceed the request limit")
        # Create the record and enqueue atomically. A separate, lease-renewed
        # seen set prevents an expired result record from replaying a write.
        created = await self.redis.eval(
            _ENQUEUE,
            4,
            key(scope, "lease"),
            key(scope, str(call.id)),
            key(scope, "seen"),
            key(scope, "queue"),
            str(call.id),
            json.dumps({"status": "queued", **json.loads(payload)}),
            bridge_settings.operation_seconds,
            bridge_settings.max_calls,
        )
        if created == -1:
            raise HTTPException(429, "Run MCP call limit reached")
        if created == -2:
            raise HTTPException(
                409, "Operation result expired; check its outcome before retrying"
            )
        if created == -3:
            raise HTTPException(410, "Sandbox MCP session ended")
        stored = await self.read(scope, str(call.id))
        if stored["tool"] != call.tool or stored["arguments"] != call.arguments:
            raise HTTPException(409, "Operation ID already used for another call")
        return {"id": str(call.id), "status": stored["status"]}

    async def read(self, scope: str, operation_id: str) -> dict:
        await self.active(scope)
        raw = await self.redis.get(key(scope, operation_id))
        if raw is None:
            raise HTTPException(404, "MCP operation not found")
        await self.redis.expire(
            key(scope, operation_id), bridge_settings.operation_seconds
        )
        return json.loads(raw)

    async def write(self, scope: str, operation_id: str, updates: dict) -> None:
        # CAS prevents expiry between GET and SET from resurrecting a partial
        # operation. A retry only updates metadata, never dispatches a tool.
        operation_key = key(scope, operation_id)
        for _ in range(3):
            raw = await self.redis.get(operation_key)
            if raw is None:
                raise HTTPException(404, "MCP operation expired")
            updated = json.dumps({**json.loads(raw), **updates})
            if await self.redis.eval(
                _UPDATE,
                1,
                operation_key,
                raw,
                updated,
                bridge_settings.operation_seconds,
            ):
                return
        raise HTTPException(409, "MCP operation changed during update")

    async def pending(self, thread_id: str, user_id: str) -> list[dict]:
        found: list[dict] = []
        for scope in await self.redis.smembers(f"sandbox-mcp:thread:{thread_id}"):
            try:
                lease = await self.active(scope)
            except HTTPException:
                continue
            if lease["user_id"] != user_id:
                continue
            operation_id = await self.redis.get(key(scope, "pending"))
            if operation_id:
                operation = await self.read(scope, operation_id)
                if operation["status"] in ("approval_required", "oauth_required"):
                    found.append({**operation, "scope": scope, "agent": lease["agent"]})
        return found

    async def decide(
        self,
        thread_id: str,
        user_id: str,
        scope: str,
        operation_id: str,
        decision: str,
        phase: str,
    ) -> None:
        lease = await self.active(scope)
        if lease["thread_id"] != thread_id or lease["user_id"] != user_id:
            raise HTTPException(404, "MCP operation not found")
        operation = await self.read(scope, operation_id)
        if operation.get("phase") != phase:
            raise HTTPException(409, "This request was already handled")
        allowed = {
            "approval_required": {"approve", "reject"},
            "oauth_required": {"reconnect", "reject"},
        }
        if decision not in allowed.get(operation["status"], set()):
            raise HTTPException(409, "This request is no longer pending")
        accepted = await self.redis.eval(
            _DECIDE,
            4,
            key(scope, "lease"),
            key(scope, operation_id),
            key(scope, "pending"),
            key(scope, f"decision:{operation_id}:{phase}"),
            operation_id,
            phase,
            operation["status"],
            decision,
            bridge_settings.operation_seconds,
        )
        if not accepted:
            raise HTTPException(
                409, "This request is no longer pending or was already answered"
            )
