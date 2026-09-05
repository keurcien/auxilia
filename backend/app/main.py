import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.agents.protocol.router import router as protocol_router
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
from app.exceptions import DomainError, root_cause, status_for
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
from app.skills.router import router as skills_router
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


# There is deliberately no `OAuthAuthorizationRequired` handler. "This MCP
# server needs authorization" is caught at the MCP seam by whoever asked to
# connect (`connectivity._open_session`, `Toolset.open`) and turned into a
# response only by the endpoints whose job is connecting — `GET
# /mcp-servers/{id}/list-tools` returns it as an `auth_required` variant, the
# run endpoints and the MCP-app endpoints answer 401 explicitly. A global one
# meant any endpoint touching MCP could answer 401 with an auth URL (design
# review §2.4).


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    """The one translation from a domain failure to a response.

    Status and body both come from `app/exceptions.py` — the table and the
    exception's own `body()` — so adding an exception is a row, not a seventh
    near-identical handler (design review §2.3).
    """
    return JSONResponse(status_code=status_for(exc), content=exc.body())


@app.exception_handler(ExceptionGroup)
async def exception_group_handler(request: Request, exc: ExceptionGroup):
    """Give a TaskGroup-wrapped domain exception the status it asked for.

    A `NotFoundError` raised under an anyio task group (the MCP transport, the
    toolset gather) arrives here inside an `ExceptionGroup`, whose MRO does not
    reach `DomainError` — so without this it would be a 500 with no detail,
    which is what the old handler produced for *every* group (design review
    §2.3).

    Keyed on `ExceptionGroup`, not `BaseExceptionGroup`: the latter is not a
    subclass of `Exception`, and Starlette asserts on that while *building the
    middleware stack* — lazily, on the first request — so registering it passes
    every import-time check and then 500s the whole app. Nothing is lost by
    narrowing, because the middleware only catches `Exception` anyway: a group
    holding a `BaseException` leaf was never going to reach a handler.

    Anything else is re-raised unchanged and becomes a logged 500. That is the
    line this handler must not cross: it exists to preserve a status the code
    already chose, never to invent one — in particular it cannot resurrect the
    global OAuth 401, because `OAuthAuthorizationRequired` is not a
    `DomainError` and the seam unwraps it long before here.

    A group can carry more than one failure — concurrent tasks that both blew
    up. The response can only be one of them, and the domain status is the
    useful one, but the rest must not vanish: they are logged in full, since a
    500 would at least have surfaced them through the server-error handler.
    """
    inner = root_cause(exc)
    if isinstance(inner, DomainError):
        _, others = exc.split(lambda leaf: leaf is inner)
        if others is not None:
            logger.error(
                "%s answered %d; the group it arrived in carried other failures, "
                "which are not in the response",
                type(inner).__name__,
                status_for(inner),
                exc_info=others,
            )
        return await domain_error_handler(request, inner)
    raise exc


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
# protocol SSE endpoint (/threads/{id}/stream/events) keeps flushing tokens
# unbuffered.
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
app.include_router(protocol_router)
app.include_router(runs_router)
app.include_router(user_runs_router)
app.include_router(auth_router)
app.include_router(tokens_router)
app.include_router(mcp_apps_router)
app.include_router(mcp_servers_router)
app.include_router(threads_router)
app.include_router(triggers_router)
app.include_router(skills_router)
app.include_router(users_router)
app.include_router(invites_router)
app.include_router(teams_router)
app.include_router(tags_router)
app.include_router(model_providers_router)
app.include_router(sandboxes_router)
app.include_router(slack_router)

app.mount("/", auxilia_mcp.streamable_http_app())
