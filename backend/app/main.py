import logging
import os
from builtins import ExceptionGroup
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.agents.router import router as agents_router
from app.auth.router import router as auth_router
from app.auth.settings import auth_settings
from app.integrations.slack.router import router as slack_router
from app.invites.router import router as invites_router
from app.mcp.apps.router import router as mcp_apps_router
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.router import auxilia_mcp
from app.mcp.servers.router import router as mcp_servers_router
from app.model_providers.router import router as model_providers_router
from app.settings import app_settings
from app.threads.router import router as threads_router
from app.users.router import router as users_router

# Redis configuration from environment variables
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

logging.getLogger("app").setLevel(app_settings.log_level.upper())

# When DEBUG, also enable MCP transport logs so we can see "GET SSE connection
# established", "Received 202 Accepted", and reconnection events alongside the
# app.timer spans.  This helps diagnose why mcp_list_tools is slow.
if app_settings.log_level.upper() == "DEBUG":
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    app.state.redis = redis_client

    async with auxilia_mcp.session_manager.run():
        yield
        await redis_client.close()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(OAuthAuthorizationRequired)
@app.exception_handler(ExceptionGroup)
async def oauth_exception_handler(_request: Request, exc: Exception):
    """Global exception handler for OAuth authorization requirements.

    Handles both direct OAuthAuthorizationRequired exceptions and those
    wrapped inside ExceptionGroups (e.g., from TaskGroups).
    """

    # 1. Check if the exception was raised directly
    if isinstance(exc, OAuthAuthorizationRequired):
        return JSONResponse(
            status_code=401,
            content={"error": "oauth_required", "auth_url": exc.url},
        )

    # 2. Check if it's an ExceptionGroup containing our target exception
    if isinstance(exc, ExceptionGroup):
        # .subgroup() searches the group (recursively) for matches
        if matching_group := exc.subgroup(OAuthAuthorizationRequired):
            # Extract the first match to get the URL
            first_match = matching_group.exceptions[0]
            return JSONResponse(
                status_code=401,
                content={"error": "oauth_required",
                         "auth_url": first_match.url},
            )

    # 3. If it's an ExceptionGroup that doesn't contain our error,
    # or an unrelated exception caught by accident, re-raise it.
    raise exc


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SessionMiddleware is required for OAuth flows (stores state during authorization)
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_settings.JWT_SECRET_KEY,
    same_site="lax",
    https_only=auth_settings.COOKIE_SECURE,
)

app.include_router(agents_router)
app.include_router(auth_router)
app.include_router(mcp_apps_router)
app.include_router(mcp_servers_router)
app.include_router(threads_router)
app.include_router(users_router)
app.include_router(invites_router)
app.include_router(model_providers_router)
app.include_router(slack_router)

app.mount("/", auxilia_mcp.streamable_http_app())

