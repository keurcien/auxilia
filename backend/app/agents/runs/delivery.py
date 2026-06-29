"""Push delivery — the seam between a run and a non-HTTP recipient.

Most runs are *pulled*: an HTTP subscriber rides the event log (`/runs/stream`).
A push channel (e.g. Slack) has no client connection to ride, so its updates are
delivered by a worker-side consumer that subscribes to the run's event log and
relays each chunk to the channel.

This module stays channel-agnostic: it defines the consumer shape and the factory
type only. The composition root (`main.py`) injects a concrete factory (the Slack
one), so `app/agents/runs` never imports `app/integrations`.
"""

from collections.abc import Callable
from typing import Protocol

from app.agents.runs.state import RunRecord


class DeliveryConsumer(Protocol):
    """Relays a run's event log to a push channel, end to end."""

    async def run(self) -> None: ...


# Built once per run from its record; returns `None` when the record has no push
# delivery (the common case — a pull subscriber handles it instead).
DeliveryFactory = Callable[[RunRecord], DeliveryConsumer | None]
