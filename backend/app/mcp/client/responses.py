"""The one place the `oauth_required` 401 body is built.

Clients branch on the exact `error` / `auth_url` keys, so the shape is a
contract shared by the run endpoints and the MCP-app endpoints. It lives here
rather than in either router because two copies of a wire format drift.

This is *not* a global exception handler — the point of design review §2.4 is
that only an endpoint whose job involves connecting may answer this, and each
one does so explicitly. Endpoints that can return the requirement as ordinary
data (`list-tools`) use the `auth_required` schema variant instead.
"""

from fastapi.responses import JSONResponse


def oauth_required_response(auth_url: str) -> JSONResponse:
    """401 telling the client which authorize URL to open."""
    return JSONResponse(
        status_code=401, content={"error": "oauth_required", "auth_url": auth_url}
    )
