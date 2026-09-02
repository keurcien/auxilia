"""Agent Streaming Protocol (issue #309, Parts 2–3).

The `@langchain/react` stack speaks a thread-centric, delta-based protocol:
`POST /threads/{id}/commands`, `POST /threads/{id}/stream/events`,
`GET /threads/{id}/state`. This package is both ends of it on the server:

- **Emission** (`emit.py`): the run worker drives the agent through
  langgraph's `astream_events(version="v3")`, which produces the protocol
  grammar natively; `ProtocolEmitter` applies the publish-side policies the
  web client's contract needs (see its module docstring) and the durable
  runtime stores one JSON event per log entry (`wire.py`).
- **Relay** (`service.py` / `router.py`): a stream session filters the stored
  events through the client's sink (`filter.py`) and stamps replay cursors
  from the log entry ids. Nothing is translated on read.
- **Terminal** events are owned by `RunService.finalize` (`terminal_lifecycle`
  in `events.py`), so the worker, the reaper and an expired-log reattach all
  end a run with the same single event.

The Slack delivery consumer reads the same stored events
(`app/integrations/slack/consumer.py`).
"""
