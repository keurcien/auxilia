"""`CheckpointState` stand-ins for tests that never run a graph.

The HITL, protocol-state and run-service tests describe a thread as "these
messages, paused on these interrupts" per checkpoint namespace. Building that
as real checkpoints would mean running a graph per case; this shapes it
directly as what `get_checkpoint_state` would return, and the test modules
patch `get_checkpoint_state` to answer from a namespace map.
"""

from types import SimpleNamespace

from app.agents.checkpoints import CheckpointState


def checkpoint_state(
    messages=(),
    *,
    interrupts: list[tuple[str, object, str | None]] | None = None,
    pending_writes: list | None = None,
    values: dict | None = None,
) -> CheckpointState:
    """A checkpoint holding `messages`, paused on `interrupts` —
    ``(task_id, value, interrupt_id)`` triples, one pending write each.
    `pending_writes` adds raw writes (e.g. a `tools` task's ToolMessage)."""
    writes = list(pending_writes or [])
    for task_id, value, interrupt_id in interrupts or []:
        writes.append(
            (task_id, "__interrupt__", [SimpleNamespace(value=value, id=interrupt_id)])
        )
    saved = SimpleNamespace(pending_writes=writes, checkpoint={"channel_values": {}})
    return CheckpointState(
        saved=saved, values={"messages": list(messages), **(values or {})}
    )
