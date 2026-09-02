"""The run event log's wire codec: one JSON protocol event per log entry.

The worker stores *event data* (`{method, params}`) as JSON; the stream
endpoint wraps each stored event into the protocol `Message` envelope
`{type: "event", event_id, seq, method, params}` when it relays it. Replay
cursors are derived from the Redis stream entry id the event was stored
under, which is what makes them free of any producer-side state:

- `event_id` is the entry id itself — unique across every run, since Redis
  stream ids are unique per instance, and stable across sessions so the
  client's replay dedup works.
- `seq` is a JS-safe monotonic encoding of the entry id (see
  `seq_for_entry`). Entry ids are minted by Redis in insertion order, so
  `seq` is monotonic across a thread's runs without any counter shared
  between the worker that publishes tokens and the reaper/`finalize` that
  publish the terminal event.

A legacy-format entry (the pre-protocol `event: …\ndata: …` SSE string,
possible only for a run in flight during the deploy that introduced this
codec) decodes to `None` and is skipped by every reader; the `_END` marker
on the log's last entry is format-agnostic, so such a run still terminates.
"""

import json
from typing import Any

from app.agents.protocol.events import terminal_lifecycle
from app.agents.protocol.messages import json_default


#: 2020-01-01 UTC. Offsetting the entry timestamp keeps the encoded seq
#: below Number.MAX_SAFE_INTEGER (2^53) until ~2055 while leaving 13 bits
#: for the per-millisecond counter.
_SEQ_EPOCH_MS = 1_577_836_800_000
_SEQ_COUNTER_BITS = 13  # 8,192 entries per millisecond


def encode_event(event: dict) -> str:
    """JSON for one protocol event (`{method, params}`), as stored in the log."""
    return json.dumps(event, default=json_default, separators=(",", ":"))


def decode_event(raw: str) -> dict | None:
    """The stored protocol event, or `None` for an entry this codec doesn't
    own (a legacy SSE chunk, or garbage)."""
    if not raw or raw[0] != "{":
        return None
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(event, dict) or "method" not in event or "params" not in event:
        return None
    return event


def encode_terminal(run_status: str, *, error: str | None = None) -> str:
    """The stored form of the root terminal lifecycle event `finalize` appends."""
    return encode_event(terminal_lifecycle(run_status, error=error))


def seq_for_entry(entry_id: str) -> int:
    """A monotonic, JS-safe sequence number derived from a Redis stream entry
    id (`<ms>-<counter>`). The counter field is 13 bits: even pipelined
    `publish_many` bursts stay far below 8,192 entries in one millisecond,
    and a hypothetical overflow saturates (ties, never reordering). A
    synthetic id (expired-log terminals) degrades to 0."""
    ms_str, _, counter_str = entry_id.partition("-")
    try:
        ms = int(ms_str)
        counter = int(counter_str or 0)
    except ValueError:
        return 0
    offset_ms = max(ms - _SEQ_EPOCH_MS, 0)
    return (offset_ms << _SEQ_COUNTER_BITS) + min(counter, (1 << _SEQ_COUNTER_BITS) - 1)


def frame(event: dict, *, entry_id: str) -> str:
    """The SSE frame for one protocol event stored under `entry_id`. The
    `id:` line mirrors `event_id` for standard SSE tooling; the client reads
    the JSON."""
    envelope: dict[str, Any] = {
        "type": "event",
        "event_id": entry_id,
        "seq": seq_for_entry(entry_id),
        **event,
    }
    return f"id: {entry_id}\ndata: {json.dumps(envelope, default=json_default)}\n\n"
