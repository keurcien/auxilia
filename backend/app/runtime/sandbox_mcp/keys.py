"""The Redis key schema for the sandbox MCP bridge, in one place (cf. runs/keys.py).

A *scope* is the hash of a run capability token: the sandbox only ever holds
the token, Redis only ever holds the hash. Every key below is per scope except
the thread index (which scopes belong to a thread, for hydration) and the
interrupt lookup (which scope/operation a protocol interrupt id answers).
"""

import hashlib


def scope_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lease_key(scope: str) -> str:
    """The capability record: thread, user, agent and allowed tools. Its
    presence is the bridge being open; the worker renews it, run end deletes it."""
    return f"sandbox-mcp:{scope}:lease"


def queue_key(scope: str) -> str:
    """Operation ids awaiting the worker (BLPOP target)."""
    return f"sandbox-mcp:{scope}:queue"


def seen_key(scope: str) -> str:
    """Every operation id ever accepted, so an expired result cannot be replayed."""
    return f"sandbox-mcp:{scope}:seen"


def operation_key(scope: str, operation_id: str) -> str:
    """One operation record (status, tool, arguments, result path or error)."""
    return f"sandbox-mcp:{scope}:{operation_id}"


def pending_key(scope: str) -> str:
    """The operation currently waiting on the user, if any."""
    return f"sandbox-mcp:{scope}:pending"


def decision_key(scope: str, operation_id: str, interrupt_id: str) -> str:
    """The user's answer to one wait (`interrupt_id` is unique per wait)."""
    return f"sandbox-mcp:{scope}:decision:{operation_id}:{interrupt_id}"


def thread_index_key(thread_id: str) -> str:
    """Set of scopes open on a thread — what `/state` hydration walks."""
    return f"sandbox-mcp:thread:{thread_id}"


def interrupt_key(interrupt_id: str) -> str:
    """Protocol interrupt id → the scope and operation it belongs to."""
    return f"sandbox-mcp:interrupt:{interrupt_id}"
