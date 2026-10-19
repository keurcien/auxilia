"""Capability-authenticated endpoints for the in-sandbox client (`client.py`).

Approvals and OAuth reconnects for bridge calls are *not* served here: they
ride the Agent Streaming Protocol like every other pending decision
(`input.requested` on the run's event log, `input.respond` on `/commands`,
`/state` for hydration — see `api/protocol_service.py`).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.exceptions import PayloadTooLargeError
from app.runtime.sandbox_mcp.keys import scope_of
from app.runtime.sandbox_mcp.schemas import CallRequest
from app.runtime.sandbox_mcp.service import SandboxMcpService
from app.runtime.sandbox_mcp.settings import bridge_settings


router = APIRouter(prefix="/sandbox-mcp", tags=["sandbox-mcp"])
bearer = HTTPBearer()


def sandbox_scope(auth: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    return scope_of(auth.credentials)


def get_sandbox_mcp_service() -> SandboxMcpService:
    return SandboxMcpService()


@router.get("/tools")
async def list_tools(
    scope: str = Depends(sandbox_scope),
    service: SandboxMcpService = Depends(get_sandbox_mcp_service),
):
    return (await service.get_lease(scope))["tools"]


@router.post("/calls", status_code=202)
async def create_call(
    request: Request,
    scope: str = Depends(sandbox_scope),
    service: SandboxMcpService = Depends(get_sandbox_mcp_service),
):
    await service.get_lease(scope)  # refuse before reading a body for a dead run
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > bridge_settings.max_request_bytes:
            raise PayloadTooLargeError("MCP arguments exceed the request limit")
        body.extend(chunk)
    try:
        call = CallRequest.model_validate_json(body)
    except ValidationError as exc:  # parse-time, like FastAPI's own 422
        raise HTTPException(422, "Invalid MCP call request") from exc
    return await service.create(scope, call)


@router.get("/calls/{operation_id}")
async def get_call(
    operation_id: UUID,
    scope: str = Depends(sandbox_scope),
    service: SandboxMcpService = Depends(get_sandbox_mcp_service),
):
    operation = await service.get(scope, str(operation_id))
    # Only the SDK's response contract crosses the sandbox boundary.
    return {
        field: operation[field]
        for field in ("status", "path", "error")
        if field in operation
    }
