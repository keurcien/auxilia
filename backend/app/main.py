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
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.servers.router import router as mcp_servers_router
from app.model_providers.router import router as model_providers_router
from app.threads.router import router as threads_router
from app.users.router import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    app.state.redis = redis_client
    yield

    await redis_client.close()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(ExceptionGroup)
async def oauth_exception_handler(request: Request, exc_group: ExceptionGroup):
    """Global exception handler for OAuth authorization requirements.

    Catches exception groups containing OAuthAuthorizationRequired and returns
    a 401 response with the authorization URL.
    """
    # Check if the exception group contains OAuthAuthorizationRequired
    for exc in exc_group.exceptions:
        if isinstance(exc, OAuthAuthorizationRequired):
            return JSONResponse(
                status_code=401,
                content={"error": "oauth_required", "auth_url": exc.url},
            )

    # If it's not an OAuth error, re-raise the exception group
    raise exc_group


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
app.include_router(mcp_servers_router)
app.include_router(threads_router)
app.include_router(users_router)
app.include_router(model_providers_router)