from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.mcp.client.connectivity import connect_to_server
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.responses import oauth_required_response
from app.mcp.servers.service import (
    MCPServerService,
    get_mcp_server_service,
)
from app.users.models import UserDB


router = APIRouter(tags=["mcp-apps"])


class MCPAppReadResourceRequest(SQLModel):
    uri: str


class MCPAppCallToolRequest(SQLModel):
    tool_name: str
    arguments: dict[str, Any] | None = None


@router.post("/mcp-servers/{server_id}/app/read-resource")
async def read_mcp_app_resource(
    server_id: UUID,
    body: MCPAppReadResourceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    mcp_server = await service.get_or_404(server_id)
    # terminate_on_close=False: the resource HTML embeds a sessionToken bound to
    # this MCP session; DELETEing the session would kill the token before the
    # browser uses it. Let the server expire it by TTL instead.
    try:
        async with connect_to_server(
            mcp_server, str(current_user.id), db, terminate_on_close=False
        ) as (session, _):
            return await session.read_resource(body.uri)
    except OAuthAuthorizationRequired as exc:
        # Answered explicitly rather than by an app-global handler (§2.4).
        # These endpoints act on a server the user is already using, so the
        # only expected reason to land here is a credential revoked or expired
        # since the app rendered.
        return oauth_required_response(exc.url)


@router.post("/mcp-servers/{server_id}/app/call-tool")
async def call_mcp_app_tool(
    server_id: UUID,
    body: MCPAppCallToolRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    mcp_server = await service.get_or_404(server_id)
    # terminate_on_close=False: keep the session alive for the App's follow-up
    # data requests; it expires by the server's TTL.
    try:
        async with connect_to_server(
            mcp_server, str(current_user.id), db, terminate_on_close=False
        ) as (session, _):
            return await session.call_tool(body.tool_name, body.arguments)
    except OAuthAuthorizationRequired as exc:
        # Answered explicitly rather than by an app-global handler (§2.4).
        # These endpoints act on a server the user is already using, so the
        # only expected reason to land here is a credential revoked or expired
        # since the app rendered.
        return oauth_required_response(exc.url)
