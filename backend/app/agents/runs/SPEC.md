# Durable agent runtime — spec & definitions

> Home for the entities this module introduces. Adapted from PR #89
> (`keurcien/agent-runtime`) to the current `main`; run *records* moved from
> Redis to Postgres in the `add_runs_table` migration. Naming follows
> `backend/CONVENTIONS.md`.

## Why this exists

Before this module, a run was pinned to the SSE request:
`POST /threads/{thread_id}/runs/stream` called `Agent.stream(...)` and piped
`astream` straight to the response. If the browser disconnected the turn was
lost — no server-side **Stop**, no re-attach, no recovery if the process died
mid-run.

The durable runtime makes a **run** a first-class entity with its own
lifecycle, an append-only event log, and a control channel. The HTTP request
becomes a thin *subscriber*: it relays the run's event log to the client and
can drop without affecting the run. This is also the substrate the **trigger**
feature enqueues onto (see `trigger-feature-plan.md`).

## What is a run?

A **run** is a single execution of an agent over a thread — one turn. It is
created from either a new human input or a HITL resume command, and it produces
the next LangGraph checkpoint for that thread.

A run is **not** where conversation state lives. Durable conversation state
stays in the LangGraph Postgres checkpoint (keyed by `thread_id`); the run is
the *execution envelope* around producing the next checkpoint. Long-term
telemetry (cost/tokens) goes to Langfuse, as today.

## What lives where

Storage is split by **data lifetime**, not by module:

| Concern | Store | Why |
| --- | --- | --- |
| Run record: status, replay params (`input`/`command`/`config_overrides`), error, timestamps | **Postgres** (`runs` table, `RunDB`) | durable — powers `threads.last_run_status`, trigger run history, and failure reproduction; pruned after `RUN_RETENTION_DAYS` |
| Queue + per-thread mutex | **Postgres** | claiming is an atomic `SKIP LOCKED` UPDATE; "one running run per thread" is a partial unique index (`uq_runs_one_running_per_thread`) |
| SSE event log (stream/reattach) | **Redis Stream** | per-token appends; TTL'd — it's a replay window, not a record |
| Cancel signal | **Redis list** | transient coordination |
| Worker liveness | **Redis key** (`SET … EX`) | a heartbeat every 5s would be MVCC dead-tuple churn in Postgres; a self-expiring key makes "silent = dead" free |

On a terminal transition, `RunService.finalize` updates the run row **and**
stamps `threads.last_run_status` in one transaction — the run outcome and the
thread badge can never disagree. Relationship: a `ThreadDB` has many `RunDB`
rows (`ondelete=CASCADE`); the worker reloads the thread and calls the existing
`Agent.build(thread, db)` to execute — the durable layer wraps `runtime.py`, it
does not replace it.

## Lifecycle (`RunStatus`)

State names match the LangGraph Server v1 wire shape (the JS SDK already speaks
them), plus `cancelled` for auxilia's explicit Stop:

| Status        | Meaning                                                        | Terminal |
| ------------- | -------------------------------------------------------------- | -------- |
| `pending`     | created, not yet claimed by a dispatcher                       | no       |
| `running`     | a worker claimed it and is streaming                           | no       |
| `interrupted` | paused on a HITL approval (`__interrupt__` pending)            | yes\*    |
| `success`     | completed cleanly                                              | yes      |
| `error`       | failed (exception, error SSE, or reaped after dead liveness)   | yes      |
| `timeout`     | exceeded `RUN_MAX_DURATION_SECONDS`                            | yes      |
| `cancelled`   | stopped via the control channel                                | yes      |

\* `interrupted` is terminal *for this run*: resuming creates a **new** run
(carrying the `Command(resume=...)`), matching how the graph checkpoint works.

The legal-transition table lives in `state.py::transition()` as the readable
spec; the repository enforces the same shape in SQL (claim:
`WHERE status='pending'`; finalize: `WHERE status NOT IN (<terminal>)`, plus an
optional `expected` guard for cancel-vs-claim races).

## Module layout (`app/agents/runs/`)

Layered like the rest of the backend (router → service → repository):

| File            | Holds                                                                                   |
| --------------- | --------------------------------------------------------------------------------------- |
| `state.py`      | `RunStatus` enum + `transition()` table — *defines a run's lifecycle*                   |
| `models.py`     | `RunDB` — the Postgres run record (String PK to match `threads.id` and Redis keys)      |
| `repository.py` | `RunRepository` — SQL: create/get/list, `claim_next` (SKIP LOCKED), guarded `finalize_run`, reaper worklists, `prune_terminal` |
| `keys.py`       | every Redis key builder — the one place the key schema is written down                  |
| `events.py`     | `RunEventStream` — Redis Streams: `publish(sse)` / `subscribe(last_event_id)`           |
| `control.py`    | `RunControl` — cancel signal (Redis list, polled via non-blocking `LPOP`)               |
| `liveness.py`   | `RunLiveness` — self-expiring heartbeat key                                             |
| `worker.py`     | `RunWorker` (executes one claimed run) + `RunDispatcher` (claim-poll loop, semaphore)   |
| `delivery.py`   | `DeliveryConsumer` protocol + `DeliveryFactory` type — the push-delivery seam           |
| `reaper.py`     | `RunReaper` — periodic orphan recovery + daily retention prune                          |
| `service.py`    | `RunService` — orchestrates Postgres + Redis; the public API                            |
| `schemas.py`    | `RunResponse`, `RunCreate` — DTOs                                                       |
| `router.py`     | HTTP surface (create / stream / reattach / get / cancel / list)                         |
| `settings.py`   | `RunSettings` — concurrency, max duration, TTLs, heartbeat, retention                   |

Deliberate deviation from the standard layering: `RunService` does **not**
extend `BaseService` and every verb opens its own short `AsyncSessionLocal()`
transaction instead of riding `get_db` — the service is called from outside any
HTTP request (worker, reaper, Slack, trigger scanner), and even router calls
must commit before the response starts streaming. Documented here so the
deviation is intentional, not drift.

## Postgres schema (`runs`)

`RunDB`: `id` (String PK, uuid4), `thread_id` (FK → threads, CASCADE),
`user_id` (FK → users, CASCADE), `status`, `multitask_strategy`, `trigger`,
`error`, and the JSONB replay params `input` / `command` / `config_overrides` /
`output_schema` / `delivery`, plus `created_at` / `updated_at`.

Indexes:

- `ix_runs_thread_id_created_at` — run history per thread.
- `uq_runs_one_running_per_thread` — partial UNIQUE on `(thread_id) WHERE
  status = 'running'`: the per-thread mutex, transactional, no TTL races.
- `ix_runs_active` — partial on `(status, user_id) WHERE status IN
  ('pending','running')`: dispatcher claim + `/runs/active` poll + reaper.

## Redis key schema (`keys.py`)

| Key                    | Type   | Contents                                       | TTL              |
| ---------------------- | ------ | ---------------------------------------------- | ---------------- |
| `run:{run_id}:events`  | stream | append-only SSE chunks (`{"data": "<sse>"}`)   | 1h after finish  |
| `run:{run_id}:control` | list   | cancel signal (polled via non-blocking `LPOP`) | 1h after finish  |
| `run:{run_id}:alive`   | string | worker heartbeat                               | self-expiring    |

The event-stream entry IDs (Redis Stream `XADD` ids) are the **resume cursor**:
`subscribe(last_event_id)` does `XREAD` from that id, so reattach replays only
what the client missed.

## Event protocol

The worker runs the existing `Agent.stream(...)`, which already yields
fully-formed SSE strings (`event: messages\ndata: …`). Each chunk is `XADD`'d
verbatim to `run:{id}:events`. Subscribers relay the raw strings to the HTTP
response, so the wire shape on `/runs/stream` is **byte-identical** to the
pre-durable endpoint — the frontend keeps working unchanged.

A terminal sentinel SSE event (`event: end`, `data: {"status": "<terminal>"}`)
is the last entry; subscribers stop when they read it. Reattach to an
already-finished run replays the whole log including the sentinel. Reattach
*after the log expired* (>1h) yields a synthetic sentinel built from the
Postgres record — the record outlives the log.

## Execution flow

1. `RunService.create(thread_id, input|command)` → INSERT `RunDB(status=pending)`.
   `reject` strategy: a same-transaction check refuses a thread with a
   pending/running run. Returns the record (HTTP layer captures `run_id` →
   `X-Run-Id`).
2. A `RunDispatcher` (one per process, started in `lifespan`) polls
   `claim_next()` every `RUN_CLAIM_INTERVAL_SECONDS`: an atomic
   `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED)` that moves the
   oldest claimable pending run to `running`. A pending run is claimable only
   while its thread has no running run — that's the whole of the `enqueue`
   strategy. Claims are single-row on purpose (a multi-row claim could pick two
   pendings of the same thread and trip the unique index); a cross-instance
   collision on the index is treated as "nothing to claim".
3. `RunWorker.run(record)` (already claimed):
   - stamp the liveness key, start the heartbeat task.
   - open its own `AsyncSessionLocal`, `Agent.build(thread, db)`, iterate
     `agent.stream(...)`, `events.publish(chunk)` each SSE; concurrently watch
     the control channel — a cancel signal cancels the stream task.
   - finalize: pick terminal status (interrupted if `__interrupt__` pending,
     else success / error / cancelled / timeout) →
     `RunService.finalize`: one transaction (run row + `threads.last_run_status`),
     then the `end` sentinel + TTL the Redis ephemera.
4. Subscribers (`/runs/stream`, `/runs/{run_id}/stream`) `subscribe(last_event_id)`
   and relay until the sentinel.

Distribution: any instance's dispatcher can claim any run; the partial unique
index keeps a thread to one running run cluster-wide. Cluster capacity =
`instances × RUN_WORKER_CONCURRENCY`.

## Push delivery (sources with no client connection)

Most consumers **pull**: an HTTP request rides the event log (`/runs/stream`) and
can drop without affecting the run. Slack has no client connection to ride, so it
is **pushed**: the worker spawns a `DeliveryConsumer` that subscribes to the run's
event log and relays each chunk to the channel.

- A run carries an opaque `delivery` descriptor (`RunDB.delivery`); `None`
  means pull. The schema is owned by the channel (Slack writes
  `{"channel": "slack", "channel_id": "C…", "thread_ts": "…", "slack_user_id": "U…", "team_id": "T…"}`),
  not by this module — `app/agents/runs` never imports `app/integrations`.
- The composition root (`main.py`) injects a `DeliveryFactory` into
  `RunDispatcher` → `RunWorker`. The worker builds a consumer from the claimed
  record (if the factory returns one) and runs it concurrently with the stream,
  awaiting it after `finalize` publishes the `end` sentinel.
- Delivery is best-effort: a consumer crash is logged and never changes the run's
  terminal status.
- The Slack consumer (`app/integrations/slack/consumer.py`) parses the canonical
  LangGraph SSE log via `SlackStreamAdapter`, streams text/tool labels through
  `chat.startStream`/`appendStream`/`stopStream`, and on the terminal event posts
  approval blocks (interrupted) or the auxilia link (success).

## Multitask strategy (per thread)

`reject` (default) — creating a run while one is pending/running for the thread
raises `DomainValidationError`. `enqueue` — the new run waits as `pending`; the
claim query skips it until the thread's running run finalizes. No requeue loop,
no backoff — waiting is a property of the data. (`interrupt`/`rollback` from
the SDK are out of scope for v1; document if/when added.)

## Thread status (`threads.last_run_status`)

The outcome of a thread's most recent run, stamped in the same transaction as
the run's terminal update. `NULL` = no finished run recorded (pre-migration
threads; no backfill). The frontend badges `error`/`timeout` in the sidebar,
suppressed while the thread has an active run; "busy" is deliberately **derived**
from the `/runs/active` poll, never stored (a stored busy flag would go stale
with its worker — cf. LangGraph Server's `ThreadStatus`, which we project, not
copy).

## Reaper

`RunReaper` runs periodically (sibling of the dispatcher, started in `lifespan`):

- `running` whose liveness key is gone AND whose last transition is older than
  `RUN_HEARTBEAT_TIMEOUT_SECONDS` (grace for the claim → first-stamp gap) →
  `error` via `finalize` (sentinel + thread stamp included).
- `pending` older than `RUN_PENDING_TIMEOUT_SECONDS` **whose thread isn't
  busy** → `error` (queued zombie). A pending run behind a running one is a
  legitimate `enqueue` waiter, however old.
- `interrupted` is never reaped.
- Daily retention pass: DELETE terminal rows older than `RUN_RETENTION_DAYS`.
  Safe by construction — `threads.last_run_status` is denormalized, so pruning
  never breaks the badge.

## Settings (`RunSettings`, env-prefixed)

| Env                              | Default | Meaning                                           |
| -------------------------------- | ------- | ------------------------------------------------- |
| `RUN_WORKER_CONCURRENCY`         | 8       | max concurrent runs per process                   |
| `RUN_MAX_DURATION_SECONDS`       | 1800    | wall-clock cap per run (0 disables)               |
| `RUN_CLAIM_INTERVAL_SECONDS`     | 0.5     | idle dispatcher poll cadence (dispatch latency)   |
| `RUN_HEARTBEAT_INTERVAL_SECONDS` | 5       | worker liveness stamp cadence                     |
| `RUN_HEARTBEAT_TIMEOUT_SECONDS`  | 30      | liveness key TTL / reaper grace for `running`     |
| `RUN_PENDING_TIMEOUT_SECONDS`    | 600     | reaper threshold for stuck `pending`              |
| `RUN_TTL_SECONDS`                | 3600    | Redis retention for a finished run's event log    |
| `RUN_RETENTION_DAYS`             | 90      | Postgres retention for terminal run rows          |
| `RUN_DISPATCHER_ENABLED`         | true    | run the in-process dispatcher + reaper            |

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

Rollout from the Redis-records version: no data migration — the old Redis
record keys were 1h-TTL ephemeral and simply expire; in-flight runs at deploy
time are reaped on the next boot, same as any deploy.
