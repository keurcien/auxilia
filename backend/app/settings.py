from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class AppSettings(BaseSettings):
    database_url: str = "postgresql+psycopg://auxilia:auxilia@localhost:5432/auxilia"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    backend_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    # Max concurrent agent runs *per instance*. Enforced by a semaphore in
    # the dispatcher (``app.agents.runs.worker.RunDispatcher``): one BRPOP
    # loop spawns a task per run up to this ceiling, blocks when saturated,
    # resumes when a slot frees. Horizontal scaling multiplies this — cluster
    # capacity = ``instances × run_worker_concurrency``.
    # Workers are mostly async-idle awaiting LLM/MCP HTTP, so the ceiling
    # can be raised aggressively; bump up if queue depth grows persistently,
    # down if Postgres connections starve.
    # ``ge=1`` rejects 0 and negative values — both would crash semaphore
    # init or stall all run execution.
    run_worker_concurrency: int = Field(default=8, ge=1)
    # Hard wall-clock cap on a single agent run. Workers race a timeout
    # task against the astream loop; on hit, the run transitions to
    # ``timeout`` and the user sees a clean end event. ``0`` disables the
    # cap (not recommended in production — a runaway agent will hold its
    # dispatcher slot indefinitely). Default 30 min matches the active-run
    # mutex TTL so the reaper sweeps the same ceiling.
    run_max_duration_seconds: int = Field(default=30 * 60, ge=0)

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


app_settings: AppSettings = AppSettings()
