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
    # How often an idle dispatcher polls Postgres for claimable pending runs —
    # the upper bound on dispatch latency.
    claim_interval_seconds: float = 0.5
    # Reaper threshold: a `running` run whose liveness key is gone AND whose
    # last transition is older than this is reaped to `error`.
    heartbeat_timeout_seconds: int = 30
    # Reaper threshold: a `pending` run older than this whose thread isn't
    # busy (a never-dispatched zombie) is reaped to `error`.
    pending_timeout_seconds: int = 600
    # Redis retention for a finished run's ephemera (event log, control key) —
    # the reattach/replay window. Run *records* live in Postgres and don't
    # expire; see `retention_days`.
    ttl_seconds: int = 3600
    # How long terminal run rows are kept in Postgres before the daily prune.
    retention_days: int = 90
    # How often the reaper sweeps for orphans.
    reaper_interval_seconds: int = 15
    # Whether this process runs the in-process dispatcher + reaper. Set false on
    # request-only instances when a dedicated worker pool owns execution.
    dispatcher_enabled: bool = True

    model_config: ConfigDict = ConfigDict(
        env_prefix="run_", env_file=ROOT_ENV, extra="ignore"
    )


run_settings: RunSettings = RunSettings()
