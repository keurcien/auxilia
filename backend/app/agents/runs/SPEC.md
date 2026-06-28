# Durable agent runtime — spec & definitions

> Home for the entities this module introduces. Adapted from PR #89
> (`keurcien/agent-runtime`) to the current `main`. Naming follows
> `backend/CONVENTIONS.md`.

## Why this exists

Today a run is pinned to the SSE request: `POST /threads/{thread_id}/runs/stream`
calls `Agent.stream(...)` and pipes `astream` straight to the response. If the
browser disconnects (reload, tab close, network blip) the `astream` loop is
cancelled and the turn is lost. There is no server-side **Stop**, no way to
re-attach to an in-flight turn, and no recovery if the process dies mid-run.

The durable runtime makes a **run** a first-class, Redis-backed entity with its
own lifecycle, an append-only event log, and a control channel. The HTTP request
becomes a thin *subscriber*: it relays the run's event log to the client and can
drop without affecting the run. This is also the substrate the **trigger**
feature enqueues onto (see `trigger-feature-plan.md`).

## What is a run?

A **run** is a single execution of an agent over a thread — one turn. It is
created from either a new human input or a HITL resume command, and it produces
the next LangGraph checkpoint for that thread.

A run is **not** where conversation state lives. Durable conversation state stays
in the LangGraph Postgres checkpoint (keyed by `thread_id`); the run is the
*execution envelope* around producing the next checkpoint. Runs live only in
Redis with a TTL — they are operational state (status, event log, cancel
channel), not the system of record. Long-term telemetry (cost/tokens) goes to
Langfuse, as today.

Relationship: a `ThreadDB` (Postgres) has many runs (Redis, ephemeral). A run
references its `thread_id`; the worker reloads the thread and calls the existing
`Agent.build(thread, db)` to execute — the durable layer wraps `runtime.py`, it
does not replace it.

## Lifecycle (`RunStatus`)

State names match the LangGraph Server v1 wire shape (the JS SDK already speaks
them), plus `cancelled` for auxilia's explicit Stop:

| Status        | Meaning                                                        | Terminal |
| ------------- | -------------------------------------------------------------- | -------- |
| `pending`     | created + enqueued, not yet picked up by a dispatcher          | no       |
| `running`     | a worker claimed it and is streaming                           | no       |
| `interrupted` | paused on a HITL approval (`__interrupt__` pending)            | yes\*    |
| `success`     | completed cleanly                                              | yes      |
| `error`       | failed (exception, or reaped after stale heartbeat)            | yes      |
| `timeout`     | exceeded `RUN_MAX_DURATION_SECONDS`                            | yes      |
| `cancelled`   | stopped via the control channel                                | yes      |

\* `interrupted` is terminal *for this run*: resuming creates a **new** run
(carrying the `Command(resume=...)`), matching how the graph checkpoint works.

Allowed transitions live in `state.py::transition()`. Any other transition
raises — illegal transitions are bugs, not silent no-ops.

## Module layout (`app/agents/runs/`)

Layered like the rest of the backend (router → service → data-access), with the
Redis primitives playing the "repository" role:

| File          | Holds                                                                                  |
| ------------- | -------------------------------------------------------------------------------------- |
| `state.py`    | `RunStatus` enum, `RunRecord` (pydantic), `transition()` table — *defines a run*       |
| `keys.py`     | every Redis key builder — the one place the key schema is written down                 |
| `registry.py` | `RunRegistry` — `RunRecord` hash CRUD, active-run mutex (Lua), `list_for_thread`       |
| `events.py`   | `RunEventStream` — Redis Streams: `publish(sse)` / `subscribe(last_event_id)`          |
| `control.py`  | `RunControl` — cancel signal (Redis list, polled via non-blocking `LPOP`)              |
| `queue.py`    | `RunQueue` — FIFO dispatch: `enqueue(run_id)` / `dequeue()` (`BRPOP`)                   |
| `worker.py`   | `RunWorker` (executes one run) + `RunDispatcher` (BRPOP loop, semaphore, task-per-run) |
| `reaper.py`   | `RunReaper` — periodic orphan recovery                                                 |
| `service.py`  | `RunService` — orchestrates the primitives; the public API                             |
| `schemas.py`  | `RunResponse`, `RunCreate` — DTOs                                                       |
| `router.py`   | HTTP surface (create / stream / reattach / get / cancel / list)                        |
| `settings.py` | `RunSettings` — concurrency, max duration, TTLs, heartbeat                             |

`enqueue` / `dequeue` (queue), `publish` / `subscribe` (events), `claim_active` /
`release_active` (mutex) are **domain verbs** for this module, registered here per
CONVENTIONS §9.

Deliberate deviation from the standard layering: `RunService` is **Redis-backed,
not DB-backed**, so it does *not* extend `BaseService[ModelDB, Repository]`. The
registry/events/control/queue classes are the data-access layer; the service
composes them. Documented here so the deviation is intentional, not drift.

## Redis key schema (`keys.py`)

| Key                              | Type   | Contents                                              | TTL  |
| -------------------------------- | ------ | ----------------------------------------------------- | ---- |
| `run:{run_id}`                   | hash   | serialized `RunRecord`                                | 24h  |
| `run:{run_id}:events`            | stream | append-only SSE chunks (`{"data": "<sse>"}`)          | 24h  |
| `run:{run_id}:control`           | list   | cancel signal (polled via non-blocking `LPOP`)        | 24h  |
| `runs:queue`                     | list   | FIFO of `run_id`s awaiting a dispatcher (`BRPOP`)     | —    |
| `runs:active`                    | set    | run_ids in a non-terminal state — the reaper's worklist | live |
| `thread:{thread_id}:active_run`  | string | the active `run_id` — the per-thread mutex (`SET NX`) | live |
| `thread:{thread_id}:runs`        | zset   | `run_id`s by `created_at` (for `list_for_thread`)     | 24h  |

The event-stream entry IDs (Redis Stream `XADD` ids) are the **resume cursor**:
`subscribe(last_event_id)` does `XREAD` from that id, so reattach replays only
what the client missed.

## Event protocol

The worker runs the existing `Agent.stream(stream_adapter="langgraph")`, which
already yields fully-formed SSE strings (`event: messages\ndata: …`). Each chunk
is `XADD`'d verbatim to `run:{id}:events`. Subscribers relay the raw strings to
the HTTP response, so the wire shape on `/runs/stream` is **byte-identical** to
today — the current frontend keeps working unchanged.

A terminal sentinel SSE event (`event: end`, `data: {"status": "<terminal>"}`) is
the last entry; subscribers stop when they read it. Reattach to an already-
finished run replays the whole log including the sentinel.

## Execution flow

1. `RunService.create(thread_id, input|command)` → build `RunRecord(status=pending)`,
   `registry.create` (writes the hash, adds to the `thread.runs` zset and the
   `runs:active` set), `queue.enqueue(run_id)`. Returns the record (HTTP layer
   captures `run_id` → `X-Run-Id`). `set_status` removes from `runs:active` on a
   terminal transition.
2. A `RunDispatcher` (one per process, started in `lifespan`) `BRPOP`s `runs:queue`,
   and for each id spawns a task on a `Semaphore(RUN_WORKER_CONCURRENCY)`.
3. `RunWorker.run(run_id)`:
   - `claim_active(thread_id, run_id)` — the mutex; if held, honor multitask strategy.
   - `transition → running`, start a heartbeat task.
   - open its own `AsyncSessionLocal`, `Agent.build(thread, db)`, iterate
     `agent.stream(...)`, `events.publish(chunk)` each SSE; concurrently watch the
     control channel — a cancel signal cancels the stream task.
   - finalize: pick terminal status (interrupted if `__interrupt__` pending, else
     success / error / cancelled / timeout), publish the `end` sentinel,
     `release_active`, set TTLs.
4. Subscribers (`/runs/stream`, `/runs/{run_id}/stream`) `subscribe(last_event_id)`
   and relay until the sentinel.

Distribution: the shared `runs:queue` means any instance's dispatcher can run any
run; the per-thread mutex keeps a thread to one active run at a time. Cluster
capacity = `instances × RUN_WORKER_CONCURRENCY`.

## Multitask strategy (per thread)

`reject` (default) — creating a run while one is active for the thread raises
`DomainValidationError`. `enqueue` — the new run waits; the worker re-checks the
mutex with backoff before claiming. (`interrupt`/`rollback` from the SDK are out
of scope for v1; document if/when added.)

## Reaper

`RunReaper` runs periodically (sibling of the dispatcher, started in `lifespan`):

- `running` with a stale heartbeat (> `RUN_HEARTBEAT_TIMEOUT_SECONDS`) → `error`
  + `end` sentinel + release mutex. Covers a worker/instance that died mid-run.
- `pending` older than `RUN_PENDING_TIMEOUT_SECONDS` → `error` (queued zombie).
- `interrupted` is never reaped (cleared by the active-run TTL / a resume run).

## Settings (`RunSettings`, env-prefixed)

| Env                            | Default | Meaning                                  |
| ------------------------------ | ------- | ---------------------------------------- |
| `RUN_WORKER_CONCURRENCY`       | 8       | max concurrent runs per process          |
| `RUN_MAX_DURATION_SECONDS`     | 1800    | wall-clock cap per run (0 disables)      |
| `RUN_HEARTBEAT_INTERVAL_SECONDS` | 5     | worker heartbeat cadence                 |
| `RUN_HEARTBEAT_TIMEOUT_SECONDS`  | 30    | reaper threshold for stale `running`     |
| `RUN_PENDING_TIMEOUT_SECONDS`  | 600     | reaper threshold for stuck `pending`     |
| `RUN_TTL_SECONDS`              | 86400   | Redis retention for run keys             |
| `RUN_DISPATCHER_ENABLED`       | true    | run the in-process dispatcher + reaper   |

## Deployment (portable; Cloud Run focus)

The dispatcher + reaper are background loops, so the process must keep CPU when
not serving requests:

- **Cloud Run**: `--no-cpu-throttling` + `--min-instances >= 1`
  (`--execution-environment=gen2`). Not GCP-specific config in the app — just an
  always-on instance.
- **VM**: a `systemd` unit (the same process). **k8s**: a `Deployment` with
  `replicas >= 1`. Same image, same entrypoint — only the "keep one alive" knob
  differs per platform.

`RUN_DISPATCHER_ENABLED=false` lets you split a dedicated worker deployment from
request-serving instances later (run the dispatcher only on the worker pool)
without code changes.
