"""Agent Streaming Protocol facade (issue #309, Part 2 — backend).

Serves the thread-centric, delta-based protocol the `@langchain/react`
stack speaks (`POST /threads/{id}/commands`, `POST /threads/{id}/stream/events`,
`GET /threads/{id}/state`) as a *facade over the durable runtime*: the worker
keeps publishing the canonical legacy LangGraph SSE log, and this package
translates that log into protocol events per subscriber. The legacy SSE
endpoints, Slack delivery, and the reaper are untouched.
"""
