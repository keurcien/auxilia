"""Durable agent runs.

This package owns everything that turns a single agent invocation into a
first-class, observable, resumable entity:

- ``state``       — the run state machine (single source of truth)
- ``registry``    — Redis hash CRUD for live ``RunRecord`` data
- ``events``      — Redis Streams transport for SSE chunks
- ``control``     — cancel signals (pub/sub)
- ``queue``       — dispatch queue between API and workers
- ``patch``       — vendored dangling-tool-call patcher
- ``worker``      — the producer loop
- ``reaper``      — orphan detection
- ``service``     — domain operations (consumed by router)
- ``schemas``     — request/response DTOs
- ``router``      — FastAPI HTTP surface, LangGraph-Server-compatible

All run state lives in Redis with a 24 h TTL. Cost telemetry goes through
Langfuse; conversation history is the LangGraph checkpoint. We deliberately
do not keep a Postgres audit table — there was no consumer for it.

Layering rules (see PRD §5.5):
- ``router`` only imports ``service``.
- ``service`` composes the lower modules; never imported by them.
- ``worker`` composes ``registry`` / ``events`` / ``control`` / ``queue`` / ``patch``.
- ``patch`` is the only module that touches deepagents internals.
"""
