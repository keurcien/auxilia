from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class RunSettings(BaseSettings):
    """Durable-runtime tunables. Env vars are prefixed `RUN_` (e.g. `RUN_WORKER_CONCURRENCY`)."""

    # Max concurrent runs executed per process. Cluster capacity = instances × this.
    worker_concurrency: int = 8
    # Wall-clock cap per run; 0 disables. A run past this is finalized as `timeout`.
    max_duration_seconds: int = 1800
    # How often a running worker stamps its heartbeat.
    heartbeat_interval_seconds: int = 5
    # How often a running worker polls its control channel for a Stop — the
    # upper bound on cancel latency.
    cancel_poll_seconds: float = 1.0
    # Reaper threshold: a `running` run whose heartbeat is older than this is reaped to `error`.
    heartbeat_timeout_seconds: int = 30
    # Reaper threshold: a `pending` run older than this (a queued zombie) is reaped to `error`.
    pending_timeout_seconds: int = 600
    # Redis retention for run keys (record, events, control). Applied at
    # creation (crash backstop) and re-applied at finalize, so it must stay
    # comfortably above `max_duration_seconds` or keys expire mid-run.
    ttl_seconds: int = 3600
    # Reattach tail: how many recent SSE chunks the event stream keeps (approx
    # MAXLEN). NOT the full run history — that lives in the LangGraph checkpoint
    # (Postgres), so trimmed chunks are recoverable and this only needs to cover
    # a reconnecting client's replay gap. Kept small on purpose; tune via
    # RUN_MAX_EVENTS.
    max_events: int = 1_000
    # How often the reaper sweeps for orphans.
    reaper_interval_seconds: int = 15
    # Whether this process runs the in-process dispatcher + reaper. Set false on
    # request-only instances when a dedicated worker pool owns execution.
    dispatcher_enabled: bool = True

    model_config: ConfigDict = ConfigDict(
        env_prefix="run_", env_file=ROOT_ENV, extra="ignore"
    )


run_settings: RunSettings = RunSettings()
