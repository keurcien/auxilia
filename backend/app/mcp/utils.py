import httpx
from datetime import datetime, timezone

from mcp.shared.auth import OAuthToken

from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB


async def check_mcp_server_connected(
    mcp_server: MCPServerDB,
    user_id: str,
) -> bool:
    """Check if a single MCP server is connected for a given user.

    Returns True if:
    - The server does not require OAuth (auth_type is none or api_key), OR
    - The server requires OAuth and the token is valid, OR
    - The server requires OAuth, the token is expired, but refresh succeeds

    Returns False if:
    - No tokens are available
    - Token is expired and refresh fails
    """
    if mcp_server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
        return True

    storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))

    # 1. Get raw stored token (with absolute expires_at)
    stored_token = await storage.get_stored_token()
    if not stored_token:
        return False

    # 2. Check if token is still valid
    is_expired = (
        stored_token.expires_at is not None
        and datetime.now(timezone.utc) > stored_token.expires_at
    )

    if not is_expired:
        return True

    # 3. Token is expired — attempt refresh
    refresh_token = stored_token.token_payload.refresh_token
    if not refresh_token:
        return False

    client_info = await storage.get_client_info()
    if not client_info:
        return False

    oauth_metadata = await storage.get_oauth_metadata()
    if not oauth_metadata or not oauth_metadata.token_endpoint:
        return False

    token_url = str(oauth_metadata.token_endpoint)
    refresh_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_info.client_id,
    }
    if client_info.client_secret:
        refresh_data["client_secret"] = client_info.client_secret

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=refresh_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            return False

        new_tokens = OAuthToken.model_validate_json(response.content)
        await storage.set_tokens(new_tokens)
        return True
    except Exception:
        return False
