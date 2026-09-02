import math

from pydantic import field_validator
from pydantic_settings import BaseSettings

from app.background import MIN_INTERVAL_SECONDS
from app.settings import settings_config


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
    # Events coalesced into one pipelined append. Caps memory and pipeline
    # size; the delay below is what caps latency.
    event_buffer_max_chunks: int = 32
    # Longest an event waits in the buffer before being shipped. These are the
    # tokens a user watches appear, so this is a perceived-latency knob: raising
    # it trades smoothness for fewer Redis round trips.
    event_buffer_max_delay_ms: int = 50
    # Reattach tail: how many recent protocol events the event stream keeps
    # (approx MAXLEN). NOT the full run history — that lives in the LangGraph
    # checkpoint (Postgres), so trimmed events are recoverable and this only
    # needs to cover a reconnecting client's replay gap. Roughly one event per
    # streamed token plus a handful per superstep (no per-token state
    # snapshots since Part 3), so this covers the tail of a long answer. Tune
    # via RUN_MAX_EVENTS.
    max_events: int = 1_000
    # How long terminal run rows are kept in Postgres before the daily prune.
    retention_days: int = 90
    # How often the reaper sweeps for orphans.
    reaper_interval_seconds: int = 15
    # Whether this process runs the in-process dispatcher + reaper. Set false on
    # request-only instances when a dedicated worker pool owns execution.
    dispatcher_enabled: bool = True

    model_config = settings_config(env_prefix="run_")

    # Every interval below drives a `while` loop's sleep. Set to zero, each turns
    # its loop into a busy spin that burns a core for the life of the process —
    # and the dispatcher's and the run heartbeat's loops sleep directly, so
    # `PeriodicLoop`'s own floor does not reach them. Clamped rather than
    # rejected: an operator writing 0 means "as often as possible", and refusing
    # to boot over a config typo is the worse failure.

    @field_validator(
        "heartbeat_interval_seconds", "reaper_interval_seconds", mode="after"
    )
    @classmethod
    def _whole_second_intervals_stay_whole(cls, value: int) -> int:
        return max(value, 1)

    @field_validator("claim_interval_seconds", "cancel_poll_seconds", mode="after")
    @classmethod
    def _sub_second_intervals_stay_positive(cls, value: float) -> float:
        # `nan`/`inf` are rejected rather than clamped: `max(nan, x)` is `nan`,
        # which then becomes a sleep timeout with undefined behaviour, and `inf`
        # is a loop that never ticks again. Unlike 0 they express no intent
        # worth honouring, so failing at boot with a clear error beats a
        # dispatcher that silently stops dispatching.
        if not math.isfinite(value):
            raise ValueError("must be a finite number of seconds")
        return max(value, MIN_INTERVAL_SECONDS)


run_settings: RunSettings = RunSettings()
