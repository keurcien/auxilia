"""The Redis key schema for the durable runtime, in one place.

Every key the runs module touches is built here so the layout is auditable from
a single file. See `SPEC.md` for the table.
"""

# FIFO of run_ids awaiting a dispatcher. Shared across instances (BRPOP).
QUEUE_KEY = "runs:queue"

# Set of run_ids in a non-terminal state (pending/running). The reaper scans
# this instead of `SCAN run:*`, which would also match the :events/:control
# sub-keys and fail HGETALL with WRONGTYPE.
ACTIVE_SET_KEY = "runs:active"


def run_key(run_id: str) -> str:
    """Hash holding the serialized RunRecord."""
    return f"run:{run_id}"


def run_events_key(run_id: str) -> str:
    """Stream of SSE chunks for this run (the reattachable event log)."""
    return f"run:{run_id}:events"


def run_control_key(run_id: str) -> str:
    """List used as the cancel channel for this run (BLPOP target)."""
    return f"run:{run_id}:control"


def thread_active_run_key(thread_id: str) -> str:
    """String holding the active run_id for a thread — the per-thread mutex."""
    return f"thread:{thread_id}:active_run"


def thread_runs_key(thread_id: str) -> str:
    """Sorted set of a thread's run_ids, scored by created_at."""
    return f"thread:{thread_id}:runs"
