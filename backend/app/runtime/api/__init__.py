"""HTTP surface of the runtime.

`runs_router.py` is run CRUD, `/invoke` and `/cancel`; the `protocol_*`
modules are the Agent Streaming Protocol relay the web client speaks
(`/threads/{id}/commands`, `/stream/events`, `/state`, `/history`). They sit
here, not in `protocol/`, so the codec stays a leaf and `runs` may import it.
"""
