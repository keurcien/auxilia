"""Capability-authenticated sandbox endpoints and user-authenticated decisions."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.auth.dependencies import get_current_user
from app.runtime.sandbox_mcp.schemas import CallRequest, Decision
from app.runtime.sandbox_mcp.service import SandboxMcpService, scope_of
from app.runtime.sandbox_mcp.settings import bridge_settings
from app.users.models import UserDB


router = APIRouter(tags=["sandbox-mcp"])
bearer = HTTPBearer()


def sandbox_scope(auth: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    return scope_of(auth.credentials)


@router.get("/sandbox-mcp/tools")
async def tools(scope: str = Depends(sandbox_scope)):
    lease = await SandboxMcpService().active(scope)
    return lease["tools"]


@router.post("/sandbox-mcp/calls", status_code=202)
async def call(request: Request, scope: str = Depends(sandbox_scope)):
    broker = SandboxMcpService()
    await broker.active(scope)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > bridge_settings.max_request_bytes:
            raise HTTPException(413, "MCP arguments exceed the request limit")
        body.extend(chunk)
    try:
        call_request = CallRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid MCP call request") from exc
    return await broker.enqueue(scope, call_request)


@router.get("/sandbox-mcp/calls/{operation_id}")
async def result(operation_id: UUID, scope: str = Depends(sandbox_scope)):
    operation = await SandboxMcpService().read(scope, str(operation_id))
    # OAuth URLs and approval input belong on the trusted user's surface only.
    return {
        k: v for k, v in operation.items() if k not in ("auth_url", "arguments", "tool")
    }


@router.get("/threads/{thread_id}/sandbox-mcp/pending")
async def pending(thread_id: str, user: UserDB = Depends(get_current_user)):
    return await SandboxMcpService().pending(thread_id, str(user.id))


@router.post(
    "/threads/{thread_id}/sandbox-mcp/{scope}/{operation_id}/decision", status_code=204
)
async def decide(
    thread_id: str,
    scope: str,
    operation_id: UUID,
    body: Decision,
    user: UserDB = Depends(get_current_user),
) -> None:
    await SandboxMcpService().decide(
        thread_id, str(user.id), scope, str(operation_id), body.type, str(body.phase)
    )
