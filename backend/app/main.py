import asyncio
import logging
from builtins import ExceptionGroup
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.agents.router import router as agents_router
from app.agents.runs.reaper import RunReaper
from app.agents.runs.router import router as runs_router
from app.agents.runs.settings import run_settings
from app.agents.runs.worker import RunDispatcher
from app.auth.router import router as auth_router
from app.auth.settings import auth_settings
from app.auth.tokens.router import router as tokens_router
from app.exceptions import (
    AlreadyExistsError,
    DomainError,
    DomainValidationError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)
from app.integrations.slack.consumer import build_slack_run_consumer
from app.integrations.slack.router import router as slack_router
from app.invites.router import router as invites_router
from app.mcp.apps.router import router as mcp_apps_router
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.initialize import apply_mcp_client_patches
from app.mcp.router import auxilia_mcp
from app.mcp.servers.router import router as mcp_servers_router
from app.model_providers.router import router as model_providers_router
from app.redis_client import close_redis, get_redis
from app.sandbox.router import router as sandbox_router
from app.settings import app_settings
from app.threads.router import router as threads_router
from app.users.router import router as users_router


logger = logging.getLogger("app")
logger.setLevel(app_settings.log_level.upper())


def _log_background_crash(task: asyncio.Task) -> None:
    """Surface a crashed background loop as a single ERROR line (a swallowed
    exception would otherwise silently stop the dispatcher or reaper)."""
    if task.cancelled():
        return
    if exc := task.exception():
        logger.error("Background task %s crashed: %r", task.get_name(), exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_mcp_client_patches()
    app.state.redis = get_redis()

    # The dispatcher + reaper are background loops; they need an always-on
    # instance with CPU allocated (Cloud Run: --no-cpu-throttling, min-instances>=1).
    # Set RUN_DISPATCHER_ENABLED=false on request-only instances.
    background: list[asyncio.Task] = []
    dispatcher: RunDispatcher | None = None
    reaper: RunReaper | None = None
    if run_settings.dispatcher_enabled:
        dispatcher = RunDispatcher(delivery_factory=build_slack_run_consumer)
        reaper = RunReaper()
        background = [
            asyncio.create_task(dispatcher.run(), name="run-dispatcher"),
            asyncio.create_task(reaper.run(), name="run-reaper"),
        ]
        for task in background:
            task.add_done_callback(_log_background_crash)

    async with auxilia_mcp.session_manager.run():
        try:
            yield
        finally:
            if dispatcher is not None:
                await dispatcher.stop()
            if reaper is not None:
                reaper.stop()
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            await close_redis()


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
                content={"error": "oauth_required", "auth_url": first_match.url},
            )

    # 3. If it's an ExceptionGroup that doesn't contain our error,
    # or an unrelated exception caught by accident, re-raise it.
    raise exc


@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": exc.detail})


@app.exception_handler(AlreadyExistsError)
async def already_exists_handler(_request: Request, exc: AlreadyExistsError):
    return JSONResponse(status_code=409, content={"detail": exc.detail})


@app.exception_handler(DomainValidationError)
async def domain_validation_error_handler(
    _request: Request, exc: DomainValidationError
):
    return JSONResponse(status_code=400, content={"detail": exc.detail})


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(_request: Request, exc: PermissionDeniedError):
    return JSONResponse(status_code=403, content={"detail": exc.detail})


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(_request: Request, exc: InvalidCredentialsError):
    return JSONResponse(status_code=401, content={"detail": exc.detail})


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    return JSONResponse(status_code=500, content={"detail": exc.detail})


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
app.include_router(runs_router)
app.include_router(auth_router)
app.include_router(tokens_router)
app.include_router(mcp_apps_router)
app.include_router(mcp_servers_router)
app.include_router(threads_router)
app.include_router(users_router)
app.include_router(invites_router)
app.include_router(model_providers_router)
app.include_router(sandbox_router)
app.include_router(slack_router)

app.mount("/", auxilia_mcp.streamable_http_app())
