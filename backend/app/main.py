import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.agents.router import router as agents_router
from app.agents.runs.reaper import RunReaper
from app.agents.runs.router import router as runs_router, user_runs_router
from app.agents.runs.settings import run_settings
from app.agents.runs.worker import RunDispatcher
from app.auth.router import router as auth_router
from app.auth.settings import auth_settings
from app.auth.tokens.router import router as tokens_router
from app.background import registry as background_loops
from app.database import close_checkpointer_pool
from app.exceptions import (
    AlreadyExistsError,
    DomainError,
    DomainValidationError,
    InvalidCredentialsError,
    ModelUnavailableError,
    NotFoundError,
    PermissionDeniedError,
)
from app.integrations.langfuse.callback import flush_langfuse
from app.integrations.slack.consumer import build_slack_run_consumer
from app.integrations.slack.router import router as slack_router
from app.invites.router import router as invites_router
from app.mcp.apps.router import router as mcp_apps_router
from app.mcp.client.initialize import apply_mcp_client_patches
from app.mcp.router import auxilia_mcp
from app.mcp.servers.router import router as mcp_servers_router
from app.model_providers.router import router as model_providers_router
from app.redis_client import close_redis, get_redis
from app.sandbox.router import sandboxes_router
from app.settings import app_settings
from app.tags.router import router as tags_router
from app.teams.router import router as teams_router
from app.threads.router import router as threads_router
from app.triggers.router import router as triggers_router
from app.triggers.scanner import TriggerScanner
from app.triggers.settings import trigger_settings
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
    # Loops register themselves on construction, so start from empty: a test
    # app (or a reload) would otherwise accumulate entries for loops that no
    # longer exist and report the instance unhealthy for ever.
    background_loops.clear()

    # The dispatcher + reaper are background loops; they need an always-on
    # instance with CPU allocated (Cloud Run: --no-cpu-throttling, min-instances>=1).
    # Set RUN_DISPATCHER_ENABLED=false on request-only instances.
    background: list[asyncio.Task] = []
    dispatcher: RunDispatcher | None = None
    reaper: RunReaper | None = None
    scanner: TriggerScanner | None = None
    if run_settings.dispatcher_enabled:
        dispatcher = RunDispatcher(delivery_factory=build_slack_run_consumer)
        reaper = RunReaper()
        background = [
            asyncio.create_task(dispatcher.run(), name="run-dispatcher"),
            asyncio.create_task(reaper.run(), name="run-reaper"),
        ]
        # The scanner enqueues onto the run queue, so it only runs where the
        # dispatcher does (always-on worker instances).
        if trigger_settings.scanner_enabled:
            scanner = TriggerScanner()
            background.append(
                asyncio.create_task(scanner.run(), name="trigger-scanner")
            )
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
            if scanner is not None:
                scanner.stop()
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            # Ship buffered traces before the instance is frozen. Langfuse
            # batches spans on a background timer, and on Cloud Run there is no
            # timer left once the last request drains — without this, the tail
            # of every scale-to-zero cycle is lost. Runs in a thread: the SDK's
            # flush is blocking, and this is the event loop's last breath.
            await asyncio.to_thread(flush_langfuse)
            await close_checkpointer_pool()
            await close_redis()


app = FastAPI(lifespan=lifespan)


# There is deliberately no `OAuthAuthorizationRequired` handler, and no
# `ExceptionGroup` handler. "This MCP server needs authorization" is caught at
# the MCP seam by whoever asked to connect (`connectivity._open_session`,
# `Toolset.open`) and turned into a response only by the endpoints whose job is
# connecting — `GET /mcp-servers/{id}/list-tools` returns it as an
# `auth_required` variant, the run endpoints and the MCP-app endpoints answer
# 401 explicitly. The global pair had two costs: any endpoint touching MCP could
# answer 401 with an auth URL, and the `ExceptionGroup` registration swallowed
# TaskGroup-wrapped *domain* exceptions into 500s (design review §2.3, §2.4).


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


@app.exception_handler(ModelUnavailableError)
async def model_unavailable_handler(_request: Request, exc: ModelUnavailableError):
    # Machine-readable body (like oauth_required) so clients can branch on
    # `error` instead of string-matching the detail.
    return JSONResponse(
        status_code=409,
        content={
            "error": "model_unavailable",
            "model_id": exc.model_id,
            "detail": exc.detail,
        },
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(_request: Request, exc: PermissionDeniedError):
    return JSONResponse(status_code=403, content={"detail": exc.detail})


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(_request: Request, exc: InvalidCredentialsError):
    return JSONResponse(status_code=401, content={"detail": exc.detail})


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    return JSONResponse(status_code=500, content={"detail": exc.detail})


# Browser traffic normally rides the Next.js proxy (same-origin), so CORS only
# matters for a browser pointed straight at the backend. It must name real
# origins: browsers reject `allow_origins=["*"]` together with credentials, so
# the previous wildcard config allowed nothing it appeared to allow.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[auth_settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress JSON responses (the /agents list alone runs to hundreds of KB on
# large workspaces). Starlette excludes text/event-stream by default, so the
# /runs/stream SSE endpoints keep flushing tokens unbuffered.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# SessionMiddleware is required for OAuth flows (stores state during authorization)
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_settings.JWT_SECRET_KEY,
    same_site="lax",
    https_only=auth_settings.COOKIE_SECURE,
)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    """Liveness for the instance, including its background loops.

    Returns 503 when a loop this process is supposed to be running has stopped
    ticking. That is the point: a dead dispatcher used to leave an instance
    answering 200s while no run ever executed again, so nothing recycled it and
    the deployment looked healthy while being entirely broken (§2.3).

    An instance with `RUN_DISPATCHER_ENABLED=false` registers no loops and is
    simply healthy — request-only instances are a supported deployment, not a
    degraded one.
    """
    loops = background_loops.snapshot()
    healthy = background_loops.healthy
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "loops": loops},
    )


app.include_router(agents_router)
app.include_router(runs_router)
app.include_router(user_runs_router)
app.include_router(auth_router)
app.include_router(tokens_router)
app.include_router(mcp_apps_router)
app.include_router(mcp_servers_router)
app.include_router(threads_router)
app.include_router(triggers_router)
app.include_router(users_router)
app.include_router(invites_router)
app.include_router(teams_router)
app.include_router(tags_router)
app.include_router(model_providers_router)
app.include_router(sandboxes_router)
app.include_router(slack_router)

app.mount("/", auxilia_mcp.streamable_http_app())
