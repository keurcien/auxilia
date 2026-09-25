"""Execution pipeline — everything that turns a thread's turn into tokens.

`app/agents` is the configuration domain (CRUD, bindings, permissions).
`RunSpec` (`app/agents/run_spec.py`) is the read model it hands this package;
beyond that, this package reaches into it for `AgentRepository` (to load the
spec), the `AgentMCPServerBase` model, and — inside one function in
`runs/service.py`, until the preflight extraction removes it — `AgentService`.
Nothing under `app/agents` imports from here. This package is the rest of the
path from a user message to a finished run:

- `agent.py` / `harness.py` / `toolset.py` — resolve a `RunSpec`, open MCP
  sessions and the sandbox, assemble the LangGraph graph, run one turn.
- `middleware/` — the leaf middleware the graph is assembled from.
- `checkpoints.py` / `hitl.py` — read-only views over the checkpoint.
- `protocol/` — the Agent Streaming Protocol codec (emit, wire, events,
  messages, filter). A leaf: it imports nothing from `runs`.
- `runs/` — the durable run lifecycle (record, queue, worker, reaper).
- `api/` — the HTTP surface: the runs router and the protocol relay
  (commands, SSE session, `/state`, `/history`).

Stages import leftward only; see `agents-module-design.md` for the target
shape this move is the first step towards.
"""
