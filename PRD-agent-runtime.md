# PRD — Robust Agent Runtime

**Status:** Draft
**Author:** keurcien
**Created:** 2026-05-07
**Reviewers:** engineering

---

## 1. Background

The agent runtime currently couples three things to a single HTTP request:

1. **Run execution** — `agent.astream(...)` is iterated inside the FastAPI streaming endpoint (`backend/app/threads/router.py:142`).
2. **State persistence** — the LangGraph Postgres checkpointer is opened inside the same generator (`backend/app/agents/runtime.py:229`).
3. **Client transport** — chunks are yielded directly to the SSE response.

When the SSE consumer disconnects (frontend freeze, tab close, hot reload, network blip, browser idle disconnect), Starlette cancels the async generator. `asyncio.CancelledError` propagates into `agent.astream(...)` and into LangGraph's executor, which cancels in-flight tool tasks. **Their results are never written to the checkpoint.**

The thread is left with an `AIMessage.tool_calls` entry that has no matching `ToolMessage`. The UI shows a permanently-spinning tool. The user can only "unstick" it by sending a new message, which triggers `deepagents.PatchToolCallsMiddleware` (`deepagents/middleware/patch_tool_calls.py:35`) to inject a synthetic *"Tool call X was cancelled - another message came in"* response.

### Symptoms in production

- Stuck tool spinners after frontend freezes (especially on long markdown chunks — partially mitigated by frontend throttling).
- Lost work: a long-running subagent that had already produced a useful result gets cancelled mid-write to the checkpoint, and the user has to redo it.
- Confusing UX: user thinks the agent is still working, but nothing is happening server-side.
- No way to attach to a run from a second tab or after a page reload.

### Constraints

- **Cloud Run** for compute. Instances are stateless and ephemeral; can be terminated at any time. Default request timeout 60 minutes max. CPU is throttled outside requests unless `--no-cpu-throttling` is set and `min_instances >= 1`.
- **Redis 7** is already provisioned and used by the MCP OAuth token storage.
- **Postgres 17** is the system of record (LangGraph checkpointer + application data).
- **Multi-instance**: assume a future where a single user's requests can land on different instances.

---

## 2. Goals

1. **Run survives client disconnects.** A user closing their tab, navigating away, or experiencing a UI freeze must not kill an in-flight agent run.
2. **Reattach to a running stream** from a different tab, after a page reload, or after a transient network drop, without losing chunks emitted while disconnected.
3. **Explicit, reliable cancellation** when the user clicks "Stop" — including on subagents and tool calls in flight.
4. **No dangling tool calls in the steady state.** If a run terminates abnormally (cancellation, instance death, crash), dangling tool calls must be reconciled before the thread is shown to the user.
5. **HITL approvals work across reconnects.** Approve/reject must be possible from a fresh page load on a thread that's currently interrupted.
6. **Observability**: every run has a `run_id` traceable across logs, Langfuse, frontend network panel, and the database.

## 3. Non-goals

- Distributing the LangGraph executor across instances (a single run still executes on a single Python process).
- Replacing Postgres as the LangGraph checkpoint backend.
- Supporting clients other than the auxilia web app and Slack adapter.
- Cross-thread workflows / agent fan-out beyond what `deepagents` already provides.
- Sub-second cold-start optimisation (separate concern).

---

## 4. Architecture overview

```
                 ┌────────────────────────────────────────────┐
                 │  Web client (Next.js, useStream)           │
                 │  - POST /threads/{tid}/runs  → run_id      │
                 │  - GET  /runs/{rid}/stream?last_id=...     │
                 │  - POST /runs/{rid}/cancel                 │
                 └───────────┬────────────────────┬───────────┘
                             │ SSE                │ control
                             ▼                    ▼
   ┌─────────────────────────────────────────────────────────┐
   │  FastAPI (Cloud Run web service)                        │
   │   - Stateless request handler                           │
   │   - Subscribes to Redis stream for chunks               │
   │   - Forwards chunks as SSE                              │
   └───────────┬─────────────────────────┬───────────────────┘
               │ enqueue                 │ XREAD
               ▼                         ▼
        ┌─────────────────────────────────────────┐
        │  Redis 7                                │
        │   run:{rid}             (hash, status)  │
        │   run:{rid}:events      (stream)        │
        │   run:{rid}:control     (list/set)      │
        │   thread:{tid}:active   (string, TTL)   │
        │   runs:queue            (list)          │
        └───────────┬─────────────────────────────┘
                    │ XADD
                    ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Run worker (Cloud Run worker service or same service   │
   │  with min_instances=1, --no-cpu-throttling)             │
   │   - Dequeues run from Redis                             │
   │   - Owns the agent.astream() iteration                  │
   │   - Writes chunks to run:{rid}:events                   │
   │   - Writes heartbeat to run:{rid}                       │
   │   - Writes status/interrupt/error to run:{rid}          │
   └───────────┬─────────────────────────────────────────────┘
               │
               ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Postgres (LangGraph checkpointer + app DB)             │
   └─────────────────────────────────────────────────────────┘
```

Two key inversions vs. today:

- **The run is owned by a worker, not the request.** The HTTP request becomes a thin subscriber.
- **All transport goes through Redis Streams**, which gives durability, replay, and the ability for any instance to subscribe.

---

## 5. Wire compatibility with LangGraph Server

**Hard constraint.** All HTTP endpoint paths, request/response schemas, and stream event envelopes MUST match the LangGraph Server v1 API where one exists. The frontend already consumes that API via `@langchain/langgraph-sdk/react` (see `web/src/app/(protected)/agents/[id]/chat/[threadId]/page.tsx:54-56`); matching the contract on the server side gives us reattach, replay, interrupt rendering, and run-state queries with **no client fork**. Where we extend the API (auth, MCP server linkage, agent management), extensions are **additive** — no breaking renames, no overloaded fields.

This is the single highest-leverage decision in the project. It collapses the frontend work in §18 from "rebuild the streaming hook" to "wire one more endpoint", and it means a future migration to (or from) hosted LangGraph Server is a config change rather than a rewrite.

### 5.1 Endpoints we adopt

| Endpoint | Purpose | Status |
| --- | --- | --- |
| `POST /threads/{tid}/runs` | Create a run (no streaming), return `run_id`. | New |
| `POST /threads/{tid}/runs/stream` | Create + stream in one shot. | Exists today; refactor to delegate to worker. |
| `GET /threads/{tid}/runs/{rid}/stream` | **Reattach** to a running run, optionally with `?last_event_id=…` for replay-from-offset. | New — this is the missing piece. |
| `GET /threads/{tid}/runs/{rid}` | Run metadata (status, interrupt payload, error). | New |
| `POST /threads/{tid}/runs/{rid}/cancel` | Explicit cancellation. | New |
| `GET /threads/{tid}/state` | Current checkpoint state. The SDK calls this on mount; aligning the shape lets us drop the manual rehydration in `initializeChat()`. | Partial — exists as `/threads/{tid}`; reshape. |
| `GET /threads/{tid}/runs` | List runs on a thread (audit / debug). | New |

### 5.2 Concepts we adopt

- **`MultitaskStrategy`** (`reject` / `enqueue` / `interrupt` / `rollback`) replaces the bespoke "single active run" mutex from §7. Configurable per-agent. The frontend SDK already understands these names.
- **Run state names** match LangGraph Server (`pending` / `running` / `interrupted` / `success` / `error` / `timeout`). Internal aliases (e.g. `orphaned`) collapse to `error` on the wire.
- **Stream event modes** (`messages` / `values` / `updates`) — already in `LangGraphStreamAdapter` (`backend/app/agents/stream.py`); keep verbatim.
- **`Command` shape** for HITL resume — `{ resume: {...} }`. Already in use.
- **`run_id` + `thread_id`** as the only identifiers crossing the API boundary. Internal IDs (worker, sandbox, MCP session) never leak into responses.

### 5.3 What we deliberately do *not* adopt

- LangGraph Server's auth model (Studio API keys / LangSmith). We keep our JWT-cookie + PAT scheme, gated by the same `get_current_user` dependency.
- The Assistants/Graphs registry. We have our own `AgentDB` and don't want a parallel concept.
- Cron / scheduled runs.
- Cross-thread store APIs.

### 5.4 What we still own (the glue)

- The Redis transport layer (event stream, control signals, run registry).
- The worker process (producer loop, queue dispatcher, heartbeat).
- The reaper for orphan detection.
- The `runs` audit table in Postgres.
- Cloud Run deployment topology.
- All the auxilia-specific extensions: MCP server bindings, Slack handlers, agent permissions, Langfuse tracing.

These are not provided by `langgraph` core or any LG Server OSS surface. They are what this PRD specifies and what the engineering team will build.

### 5.5 Architecture principles for the glue

The glue is small (~hundreds of lines), but it sits on the hot path of every agent run. It must be **clean, layered, and boring**. Concretely:

1. **One responsibility per module.** No module does both Redis I/O and business logic. No module does both transport and execution. The boundaries below are non-negotiable.

2. **Match the project's existing layering** (CLAUDE.md → Backend conventions): `router → service → repository → model`. The new run subsystem follows the same shape. A reviewer who knows the auth or agents module should be able to navigate the runs module without re-learning anything.

3. **Typed boundaries everywhere.** Stream events are Pydantic models, not dicts. `RunRecord` is a frozen dataclass. State transitions are an explicit enum-to-enum function in `state.py`, not scattered string comparisons.

4. **Domain exceptions only.** Routers raise nothing; services raise the existing `NotFoundError` / `ValidationError` / `PermissionDeniedError` / new `RunConflictError`. Redis / Postgres exceptions never escape the repository layer.

5. **No premature abstraction.** Do not introduce a `RunBackend` interface with one Redis implementation. Do not generalise `events.py` over arbitrary stream shapes. If a second backend ever appears, refactor then. Three similar lines beat a speculative interface.

6. **Idempotent boundaries.**
   - Cancel signal: setting the flag twice is a no-op.
   - Run creation: client retries on 5xx use a request-derived idempotency key so the same submission doesn't create two runs.
   - Heartbeat updates: monotonic `updated_at`; never go backwards.

7. **One owner per run.** Exactly one asyncio task on exactly one worker process owns a run. Cancellation, heartbeats, and event writes all flow through that owner. The owner uses `asyncio.shield` for *only* the post-cancellation cleanup — nowhere else.

8. **Observability is built in, not bolted on.** Every public method on `RunService` opens a span (`RequestTimer.aspan`); every log line is structured around `run_id` + `thread_id`; Langfuse trace IDs propagate from the HTTP request → `run_id` → producer → checkpoint metadata.

9. **Unit-testable in isolation.** Registry, events, state machine, and reaper each have their own unit tests with no Redis/Postgres dependency (use fakes). Integration tests cover the full producer loop against a real Redis container — but they are the minority.

10. **No silent retries, no silent drops.** If we trim the event stream, we emit a `truncated` event. If we cancel a tool, we patch a `ToolMessage`. If we orphan a run, we transition to `error` with a reason. The system never *appears* fine while losing state.

### 5.6 Module layout

```
backend/app/agents/runs/
├── __init__.py
├── state.py          # RunState enum, RunRecord dataclass, transition table
├── registry.py       # Redis hash CRUD: get/create/update RunRecord by run_id
├── events.py         # Redis Streams: encode, XADD, XREAD with last_event_id
├── control.py        # Cancel signal: pub/sub + idempotent flag
├── queue.py          # Run dispatch queue (Redis list); enqueue + blocking pop
├── worker.py         # Producer loop: dequeue → astream → write events
├── reaper.py         # Periodic orphan detection + dangling-tool-call patching
├── patch.py          # Vendored deepagents patch_tool_calls, callable directly
├── service.py        # RunService: create, cancel, get, list. Composes the above.
├── repository.py     # RunRepository: Postgres `runs` table CRUD (audit history).
├── models.py         # RunDB (SQLModel) for the audit table.
├── schemas.py        # RunCreate, RunResponse, RunStreamEvent (Pydantic).
└── router.py         # FastAPI endpoints. Thin; delegates to RunService.
```

A few specifics worth pinning down:

- `state.py` exports a single `transition(current, event) -> new_state` function with an explicit exhaustiveness check. Any state change anywhere in the codebase goes through it.
- `events.py` exposes `append(rid, event)` and `read(rid, last_id, block_ms)`. It does not know what events mean.
- `worker.py` composes `registry`, `events`, `control`, `queue`, `patch`. It does not import from `service.py` or `router.py`.
- `service.py` is the only module imported by `router.py`. The router has no Redis or Postgres access.
- `patch.py` is the only module that imports from `deepagents` internals; if upstream adds an `on_cancel` hook later, `patch.py` is the one file we delete.

This layering means: a bug in event serialization is a one-file edit; a bug in cancellation semantics is a one-file edit; a bug in HTTP shape is a one-file edit. No grep across the runtime.

---

## 6. Run lifecycle

### 6.1 States

| State | Meaning |
| --- | --- |
| `queued` | Run accepted, waiting for a worker to pick it up. |
| `running` | Worker is iterating `agent.astream(...)`. |
| `interrupted` | LangGraph emitted an `interrupt()`; awaiting human input. |
| `completed` | Astream finished cleanly; final state checkpointed. |
| `cancelled` | User-initiated stop or system-initiated cancel; dangling tool calls patched. |
| `errored` | Unhandled exception in the worker; thread state may need patching. |
| `orphaned` | Heartbeat missing for >N seconds; worker presumed dead. Reaper transitions to `errored` after dangling-tool-call patch. |

### 6.2 Allowed transitions

```
queued ──► running ──► completed
                  └──► interrupted ──► (new run on resume)
                  └──► cancelled
                  └──► errored
                  └──► orphaned ──► errored (after patch)
```

A new run is **always** required to resume from `interrupted` (the resume command creates a new `run_id`, same `thread_id`, picks up from the checkpoint).

### 6.3 Invariants

- At most one run per thread is in `queued`, `running`, or `interrupted` at any time.
- Every run terminates in `completed`, `cancelled`, or `errored` — none of which leave dangling tool calls.
- The Postgres checkpoint is always consistent on terminal transitions.

---

## 7. Components

### 7.1 Run registry (Redis)

Per-run hash `run:{rid}`:

| Field | Type | Notes |
| --- | --- | --- |
| `thread_id` | string | FK to threads table. |
| `user_id` | string | Originator. |
| `agent_id` | string | The agent being invoked. |
| `status` | enum | See §6.1. |
| `created_at` | ISO8601 | |
| `started_at` | ISO8601 | When worker picked up. |
| `updated_at` | ISO8601 | Bumped on every state change. |
| `heartbeat_at` | ISO8601 | Worker writes every 5s while running. |
| `worker_id` | string | Cloud Run instance ID owning the run. |
| `last_event_id` | string | Highest Redis Stream ID written; used for resume. |
| `interrupt` | JSON | Payload of the active LangGraph `interrupt()`, if any. |
| `error` | JSON | `{type, message, traceback}` if `errored`. |
| `cancellation_reason` | string | `user`, `timeout`, `replaced`, `system`. |
| `input_summary` | JSON | First user message text + attachment count, for debugging. |

Per-thread pointer `thread:{tid}:active_run` — string holding `run_id`. TTL = max run duration (default 30 min). Acts as the single-active-run mutex via `SET NX EX`.

Run history (Postgres): a new `runs` table for durable audit. Mirrors the Redis hash plus token usage, model, latency. Indexed by `(thread_id, created_at DESC)`.

### 7.2 Producer (worker)

Lives in the same Python codebase. Two deployment options:

- **V1 (recommended for first ship):** same Cloud Run service, with `--no-cpu-throttling`, `min_instances >= 1`, and an in-process worker started at boot via `lifespan` that pulls from Redis. Same image, fewer ops.
- **V2:** separate Cloud Run service (`auxilia-worker`) with stricter resource sizing.

Algorithm:

```
loop:
    rid = BLPOP runs:queue                   # blocking pop
    set run.status = running, started_at, worker_id
    spawn heartbeat task (5s interval)
    open AsyncPostgresSaver
    build agent
    spawn cancellation watcher (subscribe to run:{rid}:control)
    try:
        async for chunk in agent.astream(...):
            XADD run:{rid}:events  *  chunk
            update run.last_event_id
        if interrupt detected: status = interrupted, write interrupt payload
        else: status = completed
    except CancelledError:
        run patch_dangling_tool_calls(thread_id)   # synchronous, must succeed
        status = cancelled
    except Exception as e:
        run patch_dangling_tool_calls(thread_id)
        status = errored, error = e
    finally:
        XADD run:{rid}:events  *  {type: "end"}
        cancel heartbeat + watcher
        DEL thread:{tid}:active_run if equal to rid
```

Heartbeat: every 5s, `HSET run:{rid} heartbeat_at <now>`. Reaper marks `running` runs with stale heartbeat (>30s) as `orphaned`.

Cancellation watcher: subscribes to `run:{rid}:control` (Redis pub/sub or `BLPOP run:{rid}:control` list). On signal, calls `task.cancel()` on the astream task. The `except CancelledError` branch above handles cleanup. **Critical**: the patch step must run with `asyncio.shield()` to survive the cancellation that triggered it.

### 7.3 Consumer (SSE handler)

Two endpoints replace the current `POST /threads/{tid}/runs/stream`:

```
POST /threads/{tid}/runs              → { run_id }
GET  /runs/{rid}/stream?last_id=X     → text/event-stream
POST /runs/{rid}/cancel               → { ok: true }
GET  /runs/{rid}                      → run metadata (status, interrupt, error)
GET  /threads/{tid}/active_run        → { run_id | null }
```

`POST /threads/{tid}/runs`:
1. Validate auth + thread permission.
2. `SET NX EX 1800 thread:{tid}:active_run <new_rid>`. If fails, return `409 Conflict` with the existing `run_id` so the client can reattach.
3. Write `run:{rid}` hash with `status=queued`, `input_summary`, etc.
4. `LPUSH runs:queue <rid>` (with full input payload encoded; or store in `run:{rid}:input` and queue just the rid).
5. Return `{ run_id }`.

`GET /runs/{rid}/stream?last_id=X`:
1. Validate auth + run ownership.
2. Resolve start ID: `last_id` (client-supplied), or `0` for full replay, or `$` for tail-only.
3. Loop: `XREAD BLOCK 25000 STREAMS run:{rid}:events <id>` → forward each event as SSE. Send keepalive comment `: ping\n\n` every 15s when idle.
4. Stop on `{type: "end"}` event or client disconnect.

`POST /runs/{rid}/cancel`:
1. Validate auth.
2. Set `cancellation_reason = "user"`, `LPUSH run:{rid}:control "cancel"` (or `PUBLISH`).
3. Return immediately. The run's terminal event will reach the SSE consumer normally.

### 7.4 Reaper

A background task running on every web instance (cheap), or a single Cloud Run Cron job:

- Every 30s: `SCAN run:* MATCH run:*`, find `status in (queued, running, interrupted)` with `heartbeat_at` older than 30s.
- For `running` orphans: mark `orphaned`, run `patch_dangling_tool_calls` against the thread, set `status = errored`, write end event.
- For `queued` zombies (no worker picked up in 60s): re-enqueue or fail with `errored`.
- For `interrupted` runs: do nothing (waiting on user is fine; no heartbeat expected). Bound only by thread:active_run TTL.

### 7.5 Frontend integration

`useStream` is replaced by a custom hook that:

1. **On mount with a fresh prompt:** POSTs `/threads/{tid}/runs`, gets `run_id`, opens GET `/runs/{rid}/stream`. Tracks `lastEventId` from each Redis Stream message.
2. **On disconnect (network/transient):** auto-reopens GET `/runs/{rid}/stream?last_id=<lastEventId>`. Exponential backoff up to 30s.
3. **On page mount over an active thread:** GET `/threads/{tid}/active_run`. If a run exists and is `running` or `interrupted`, open the stream from `last_id=0` to replay all events. If `interrupted`, render the approval UI.
4. **Stop button:** POST `/runs/{rid}/cancel`. UI optimistically marks as cancelling; final state arrives via the stream.
5. **HITL approve/reject:** POSTs a new `/threads/{tid}/runs` with `command: { resume: ... }` after confirmation. Receives a new `run_id`. Same SSE flow.

The existing AI SDK message reducers stay; only the transport changes.

---

## 8. Stream event schema

All chunks are written to `run:{rid}:events` as Redis Stream entries with field `data` = JSON. Event envelope:

```json
{ "type": "messages" | "values" | "updates" | "interrupt" | "error" | "end",
  "namespace": ["coordinator"] | null,
  "payload": { ... }                              // mode-specific
}
```

The `interrupt` event includes the structured payload that the UI uses to render the approval card. The `end` event marks stream closure (one of `completed`, `cancelled`, `errored`); its payload includes the final status.

Backwards compatibility: the current `LangGraphStreamAdapter` (`backend/app/agents/stream.py`) already produces SSE-encoded events for these modes. The producer can write the *encoded* string into Redis verbatim, so the consumer just forwards bytes — minimal serialization cost.

Stream pruning: `XADD ... MAXLEN ~ 5000`. TTL on the stream key set to 24h via `EXPIRE` after `end`. Older runs replay only summary state from Postgres.

---

## 9. Cancellation

Three sources:

1. **User-initiated** — `POST /runs/{rid}/cancel`. Cancellation reason `user`.
2. **Replaced** — user submits a new run on the same thread while one is active. Server cancels the existing run before creating the new one. Reason `replaced`. (UI should warn before triggering this.)
3. **Timeout** — run exceeds max duration (default 30 min, configurable per agent). Reason `timeout`.

In all three cases the worker must:

- Receive the cancel signal on `run:{rid}:control`.
- Cancel the astream task.
- Run `patch_dangling_tool_calls(thread_id)` under `asyncio.shield` so the synthetic ToolMessages reach the checkpoint even though the parent task is being torn down.
- Emit an `end` event with `status=cancelled`.

`patch_dangling_tool_calls` is currently provided by `deepagents.PatchToolCallsMiddleware` only on `before_agent` (next turn). We need to lift the patching logic into a callable we can invoke explicitly during cancellation, so the thread is consistent **at the moment the run ends** rather than only on the next user turn. Decision needed: vendor the deepagents patch logic, or upstream a hook (`on_cancel`) — see §17.

---

## 10. Human-in-the-loop approval

`langchain.middleware.HumanInTheLoopMiddleware` already drives interrupts in the current runtime. The interrupt payload is what the frontend renders as approve/reject cards.

In the new architecture:

1. When astream emits an interrupt, the producer:
   - Writes `interrupt` payload to `run:{rid}` hash and to the events stream.
   - Sets `status = interrupted`.
   - Releases the `thread:{tid}:active_run` mutex (so the user can submit a new run that resumes the interrupt).
   - Exits cleanly.

2. The frontend renders the interrupt UI from the events stream (or by polling `GET /runs/{rid}` if reattaching after a reload).

3. User clicks Approve / Reject (possibly batched across multiple tools — already supported). Frontend POSTs a new run with `command: { resume: { decisions: [...] } }`.

4. Server creates a new run, links it to the same thread (same checkpoint). The deep agent picks up at the interrupt and continues.

Edge cases:

- **Approval race:** two browser tabs both submit approvals for the same interrupt. The second `SET NX` on `thread:{tid}:active_run` fails → the second tab reattaches to the run started by the first.
- **Approval after cancellation:** user clicks Approve after the run timed out. The interrupt no longer exists in the checkpoint; resume returns an error. Frontend treats this as a recoverable "thread state changed" and reloads.
- **Partial approval:** user approves some tools and rejects others (already handled by the message adapter; just ensure the new transport doesn't lose the per-tool decision array).

---

## 11. Error handling

| Failure | Surfaced as | Recovery |
| --- | --- | --- |
| LLM provider 5xx, transient | `error` event, `status=errored` | User can retry (regenerate). |
| LLM provider auth/quota | `error` event, classified | Surface to user; admin alert. |
| Tool exception | Already wrapped by `ToolErrorMiddleware`; becomes a `ToolMessage` with `status=error`. | Agent decides (retry, give up). No run-level action. |
| MCP server unreachable | Tool error path. | `check_mcp_server_connected` already surfaces this on agent readiness. |
| Worker OOM / SIGKILL | Heartbeat goes stale → reaper marks `orphaned` → patch + `errored`. | User sees a "run failed" state; can retry. |
| Postgres unreachable | Worker fails to open checkpointer → run errors before any chunk. | `error` event with retry hint. |
| Redis unreachable | Worker can't write to stream → log + raise; reaper picks up the orphan. | Hard failure mode; should alert. |

All error paths must end with an `end` event so the consumer's loop terminates promptly.

`error` event payload: `{ type, message, retryable: bool, code?: string }`. Frontend maps to UI:

- `retryable=true` → show "Retry" button (resends last user message).
- `retryable=false` → show error inline; require user action (e.g. reconnect MCP).

---

## 12. Reconnection contract (frontend ↔ backend)

The most important behavioural property:

> A consumer that opens `GET /runs/{rid}/stream?last_id=X` MUST receive every event with stream ID > X that was ever written, in order, until the `end` event.

This is what makes the UI seamless across reloads. Implementation requires:

- Stream entries are not pruned until `end` event + 5 minutes (replay window for slow reconnects).
- `last_event_id` is stored in `run:{rid}` so the frontend can request `last_id=0` if it doesn't have one (page reload, fresh tab) and still get the full transcript replayed.
- The `end` event itself is part of the stream, not signaled out-of-band.

Frontend loop (sketch):

```ts
let lastId = "0";
while (!terminated) {
  const res = await fetchSSE(`/runs/${rid}/stream?last_id=${lastId}`);
  for await (const evt of res.events) {
    lastId = evt.id;
    apply(evt);
    if (evt.type === "end") { terminated = true; break; }
  }
  if (!terminated) await backoff();
}
```

---

## 13. Cloud Run specifics

- **CPU always allocated** on the worker service (or web service if V1 deployment): `--no-cpu-throttling`. Without this, background asyncio work pauses between requests.
- **Min instances ≥ 1** so there's always a worker ready to dequeue. Dial up if queue depth grows.
- **Request timeout**: set web service to 60 min for the SSE endpoint specifically (or the whole service, with care). Note: even with 60 min, Cloud Run may terminate. The architecture's resilience to that termination is exactly what this PRD delivers.
- **Concurrency**: web service can stay at the default (80). Worker service should run at concurrency 1 — each instance owns one run at a time — so the autoscaler matches workers to live runs cleanly.
- **Graceful shutdown**: Cloud Run sends SIGTERM with a 10s grace period. Worker must:
  - Stop pulling new runs from `runs:queue` immediately.
  - Try to checkpoint and patch the in-flight run (best effort).
  - If grace period expires, the reaper handles the orphan on the next instance.
- **Cold starts**: a fresh worker instance must build its agent + connect to MCP servers before it can do useful work. Acceptable for V1; investigate keep-warm or per-thread agent caching later.

---

## 14. Sandbox lifecycle

The sandbox (lazy E2B-style) is created during a run when the LLM calls `create_sandbox` / `connect_sandbox`. Today the sandbox lives only for the duration of the FastAPI request. In the new architecture:

- Sandbox is owned by the worker for the duration of the run.
- On `cancelled` / `errored` / `completed`: tear down sandbox.
- On `interrupted`: the sandbox would be lost when the worker exits. Two options:
  1. **(V1)** Tear down on interrupt; the resumed run creates a fresh sandbox. Acceptable as long as agent prompts encourage `connect_sandbox` over `create_sandbox` on the next turn — the deep agent already supports persistent sandbox handles.
  2. **(V2)** Persist sandbox handle (URL + auth) in `run:{rid}` and pass to the resume run. Requires sandbox provider to support handle reuse across processes.

V1 is fine. Document the "sandbox may be recreated after HITL approval" behaviour in agent system prompts.

---

## 15. Database schema changes

New `runs` table for audit + history:

```sql
CREATE TABLE runs (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    agent_id UUID NOT NULL REFERENCES agents(id),
    status TEXT NOT NULL,
    cancellation_reason TEXT,
    error JSONB,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_id TEXT,
    input_summary JSONB,
    token_usage JSONB
);
CREATE INDEX runs_thread_id_created_at_idx ON runs (thread_id, created_at DESC);
CREATE INDEX runs_status_heartbeat_idx ON runs (status, updated_at) WHERE status IN ('queued','running','interrupted');
```

Redis is the **live** state; Postgres is the **history**. Worker writes to both on every state transition (Redis hot-path, Postgres batched). Postgres is what the admin UI / billing reports query.

---

## 16. Security

- `POST /threads/{tid}/runs` — user must have access to the thread. Already enforced by the current router.
- `GET /runs/{rid}/stream` — user must own the run (verified by `run:{rid}.user_id == current_user.id`).
- `POST /runs/{rid}/cancel` — user must own the run.
- Redis stream keys are namespaced by `run_id` (UUID); no cross-thread leakage possible without an authorization bypass.
- Input payloads (potentially sensitive) live in `run:{rid}:input`. TTL ≤ 24h. Encrypt at rest if the threat model requires it (V2).
- Rate limit: max N concurrent runs per user (default 3). Enforced by Redis counter `user:{uid}:active_runs`.

---

## 17. Open questions

1. **Worker deployment shape (V1 vs V2).** Same Cloud Run service vs separate? Recommend V1 (same service, in-process worker pool started in lifespan) for first ship; revisit when run volume warrants isolation.
2. **`patch_dangling_tool_calls` invocation.** Today this lives in `deepagents.PatchToolCallsMiddleware` on `before_agent`. We need to call it explicitly on cancellation. Vendor a copy, or upstream a hook? Recommend vendoring as `app/agents/patch.py` for now; track upstream PR.
3. **HITL approval batching across tabs.** If two tabs are open and both render the approval UI, what happens if one approves before the other? Spec says second tab reattaches; does our message adapter handle that gracefully? Needs a test.
4. **`max_run_duration` per agent.** Currently no enforcement. Add as agent config? Default 30 min.
5. **Slack adapter migration.** Slack handlers also call `runtime.stream` (`backend/app/integrations/slack/...`). Should they go through the same Redis-backed flow, or stay request-scoped? Slack runs are typically short and the disconnect-recovery story is irrelevant. Recommend leaving Slack on the in-process path until V2.
6. **Multi-region.** Not in scope but worth noting: Redis Streams across regions = async replication + lag. Pin worker + Redis to the same region.
7. **Backpressure.** If the Redis stream grows faster than the consumer reads, `MAXLEN ~ 5000` will trim from the head, causing the consumer to lose chunks. Choose: drop with a `truncated` event vs. block the producer. Recommend drop; long streams indicate a runaway agent and the user should refresh.
8. **Persistent sandbox across HITL.** See §14. V1 = tear down + recreate.

---

## 18. Phased rollout

Each phase ends with a green test suite and a deployable artefact. No phase leaves the system in a worse state than before it started.

### Phase 1 — Foundations (≈ 1 week)

Skeleton modules, no HTTP surface yet. The goal is a unit-tested run subsystem that nothing yet calls.

- [ ] `runs` table migration (§15) + `RunDB` model + `RunRepository`.
- [ ] `app/agents/runs/state.py` — `RunState` enum + `transition()` table; exhaustive unit tests.
- [ ] `app/agents/runs/registry.py` — Redis hash CRUD around `RunRecord`.
- [ ] `app/agents/runs/events.py` — Redis Streams `append` / `read` with `last_event_id`.
- [ ] `app/agents/runs/control.py` — cancel signal pub/sub.
- [ ] `app/agents/runs/queue.py` — dispatch queue.
- [ ] `app/agents/runs/patch.py` — vendored dangling-tool-call patcher, idempotent.
- [ ] Each module has its own unit tests with fakes; no real Redis required.

### Phase 2 — Worker + endpoints (≈ 1 week)

The runtime starts producing real runs; the LangGraph-Server-shaped HTTP surface goes live.

- [ ] `app/agents/runs/worker.py` — producer loop composing the Phase 1 modules. Heartbeat + cancellation watcher. `asyncio.shield` only around post-cancel cleanup.
- [ ] Lifespan integration: start N producer tasks at app boot (configurable; default 1).
- [ ] `app/agents/runs/service.py` + `router.py` — LG-compatible endpoints (§5.1):
      `POST /threads/{tid}/runs`, `POST /threads/{tid}/runs/stream`,
      `GET /threads/{tid}/runs/{rid}/stream`, `GET /threads/{tid}/runs/{rid}`,
      `POST /threads/{tid}/runs/{rid}/cancel`, `GET /threads/{tid}/runs`.
- [ ] `MultitaskStrategy` enforcement (§5.2) on run creation.
- [ ] `app/agents/runs/reaper.py` periodic task.
- [ ] Integration tests against a real Redis container: cancel, reattach with `last_event_id`, orphan→error transition, HITL interrupt → resume creates a new run.
- [ ] Existing `POST /threads/{tid}/runs/stream` reroutes through the service; identical SSE shape preserved.

### Phase 3 — Frontend wiring (≈ 2 days)

Drastically smaller than originally scoped: because we adopt the LangGraph Server contract (§5), `@langchain/langgraph-sdk/react`'s `useStream` already handles reattach, replay, and interrupt rendering. We do not fork it.

- [ ] Confirm `useStream` reattaches via `GET /threads/{tid}/runs/{rid}/stream` against our backend (smoke test in dev).
- [ ] Drop the manual `initializeChat()` rehydration once `GET /threads/{tid}/state` returns the SDK-shaped payload.
- [ ] Stop button → `POST /runs/{rid}/cancel`.
- [ ] On `interrupted` runs surfaced by reattach, render the existing approval UI (it already keys off `interrupt`).
- [ ] Remove the now-obsolete "send a message to unstick" UX path; reattach + reaper + at-end patching make it unnecessary.

### Phase 4 — Hardening (≈ 1 week)

- [ ] Langfuse trace IDs flow through `run_id` end-to-end.
- [ ] Metrics: runs/sec, p95 run duration, cancel rate, orphan rate, reconnect rate, queue depth.
- [ ] Load test: 100 concurrent runs; validate Redis stream throughput and worker autoscaling.
- [ ] Cloud Run config: `--no-cpu-throttling`, min instances, concurrency tuning per §13.
- [ ] Runbook: recovering stuck Redis state, re-issuing a run from a checkpoint, draining workers for deploys.

### Phase 5 — Cleanup

- [ ] Delete the legacy in-process `runtime.stream` path once Phase 3 is in production.
- [ ] Migrate or delete `runtime.invoke` (`POST /threads/{tid}/runs/invoke`) — currently used by tests only.
- [ ] Re-evaluate worker isolation (V2 separate `auxilia-worker` Cloud Run service) once run volume justifies it.

---

## 19. Out of scope for this PRD

- Slack adapter migration to Redis-backed runs.
- Cross-instance run resurrection (a worker dying and another picking up the *same* run mid-flight from the LangGraph checkpoint). Today: dying worker → orphaned → user retries.
- Per-tool streaming progress within a single run (partial tool output).
- Agent-to-agent direct invocation outside of `deepagents` subagents.

---

## Appendix A — Comparison with status quo

| Concern | Today | After this PRD |
| --- | --- | --- |
| Run survives client disconnect | No | Yes |
| Reattach from new tab / reload | No | Yes |
| Explicit cancellation | Implicit (close tab) | Explicit, audited |
| Dangling tool calls | Patched only on next user turn | Patched at end-of-run |
| Single active run per thread | Best-effort (client-driven) | Enforced server-side |
| Audit trail | Checkpoint only | `runs` table + Redis live state |
| HITL across reloads | Lost on reload | Preserved |
| Multi-instance ready | No | Yes (consumer side; producer still single-instance per run) |

## Appendix B — Glossary

- **Run** — one execution of `agent.astream(...)` for a given thread. May span multiple tool calls and many seconds of wall time.
- **Thread** — a persistent conversation with a LangGraph checkpoint. A thread has many runs over its lifetime.
- **Checkpoint** — LangGraph's serialized graph state in Postgres. Source of truth.
- **Event stream** — Redis Stream of chunks emitted during a run. Ephemeral (24h TTL).
- **Worker** — Python process executing a run. May be the web instance (V1) or a dedicated service (V2).
