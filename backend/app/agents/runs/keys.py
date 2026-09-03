"""The Redis key schema for the durable runtime, in one place.

Run *records* live in Postgres (`RunDB`); Redis holds only per-run ephemera —
the event log, the cancel channel, and the liveness key. Every key the runs
module touches is built here so the layout is auditable from a single file.
"""


def run_events_key(run_id: str) -> str:
    """Stream of protocol events for this run (the reattachable event log)."""
    return f"run:{run_id}:events"


def run_control_key(run_id: str) -> str:
    """List used as the cancel channel for this run (LPOP target)."""
    return f"run:{run_id}:control"


def run_alive_key(run_id: str) -> str:
    """Self-expiring worker heartbeat; a missing key on a `running` run means
    its worker died (the reaper's signal)."""
    return f"run:{run_id}:alive"


def dispatchers_alive_key() -> str:
    """Self-expiring key stamped by every live `RunDispatcher` in the cluster.

    Answers exactly one question for the reaper: is anything out there able to
    claim runs? Deliberately one shared key rather than one per instance — the
    reaper never needs to know *which* dispatcher is alive, and a shared key
    means the check is one EXISTS instead of a SCAN.
    """
    return "run:dispatchers:alive"
