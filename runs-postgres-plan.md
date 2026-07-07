# Runs in Postgres + thread last-run status — implementation plan

## Goal

Make run outcomes durable and thread error state visible:

1. Move **run records** (status, params, error) from Redis to a Postgres `runs` table —
   Postgres becomes the source of truth for what a run *is* and how it ended.
2. Stamp **`threads.last_run_status`** transactionally when a run reaches a terminal state —
   powers the sidebar error badge and the trigger run-history view.
3. Keep Redis for what it's good at: the **SSE event log**, the **cancel signal**, and
   **worker liveness** — high-frequency, ephemeral coordination with no audit value.

This supersedes `thread-last-run-status-plan.md` (the column-only plan). The public
`RunService` verbs and every HTTP endpoint keep their current shape — this is a storage-layer
swap inside `app/agents/runs/`.

## What lives where

| Concern | Store | Writes |
| --- | --- | --- |
| Run record: status, input/command, config, error, timestamps | **Postgres** `runs` | 3 per run: INSERT `pending` → claim `running` → terminal |
| Thread outcome: `threads.last_run_status` | **Postgres** | 1 per run, same transaction as the terminal update |
| Queue + per-thread mutex | **Postgres** (`SKIP LOCKED` claim + partial unique index) | part of the claim |
| SSE event log (stream, reattach, end sentinel) | **Redis Streams** — unchanged (`events.py`) | per chunk |
| Cancel signal | **Redis** — unchanged (`control.py`) | rare |
| Worker liveness (heartbeat) | **Redis**: `run:{id}:alive` key, `SET EX <timeout>` every 5s | in-place, self-expiring |

Rationale for the split: Postgres UPDATEs are MVCC row versions (heartbeats every 5s would be
pure dead-tuple churn), while Redis TTL keys make "no heartbeat = presumed dead" a property of
the key. Postgres holds only state *transitions*; Redis holds signals whose relevance expires
in seconds.

## Data model

### `runs` table — `RunDB(BaseDBModel)` in `app/agents/runs/models.py`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | from `BaseDBModel` (run ids are already `uuid4` strings on the wire) |
| `thread_id` | String FK → `threads.id` | indexed |
| `user_id` | UUID FK → `users.id` | |
| `status` | String | `RunStatus` values; transitions still validated by `state.transition` |
| `multitask_strategy` | String | `reject` (default) / `enqueue` |
| `trigger` | String, nullable | e.g. `regenerate-message` |
| `error` | Text, nullable | terminal error text |
| `input`, `command`, `config_overrides`, `output_schema`, `delivery` | JSONB, nullable | the replay parameters, verbatim from today's `RunRecord` |
| `created_at`, `updated_at` | from `TimestampMixin` | `updated_at` at terminal = finish time |

Indexes:

- `(thread_id, created_at DESC)` — run history per thread.
- **Partial UNIQUE on `(thread_id) WHERE status = 'running'`** — this *is* the per-thread
  mutex, transactional, no TTL races. Replaces `claim_active`/`release_active`/Lua.
- Partial on `(status) WHERE status IN ('pending','running')` — queue claim + active-runs poll.

### `threads.last_run_status`

- `String`, nullable. Values: `success` / `error` / `timeout` / `cancelled` / `interrupted`.
- `NULL` = no finished run recorded (all pre-migration threads; no backfill — we don't care
  about past threads).
- On `ThreadDB` only (not `ThreadBase`): server-stamped, never client-supplied. No error-text
  column — the message lives on the run row now.

### Migration

Hand-written Alembic revision (do not autogenerate — the shared dev DB has orphan tables):
`op.create_table("runs", ...)` + indexes, `op.add_column("threads", ...)`. **No data
migration**: run records were 1h-TTL ephemeral; old Redis keys just expire.

## Lifecycle mechanics

### Create (`RunService.create`)

INSERT with `status='pending'`. `reject` strategy: same-transaction existence check for a
pending/running run on the thread → `DomainValidationError` (Slack's skip behavior and the
router contract are unchanged). The partial unique index backstops the running state; a racing
double-create under `reject` degrades to sequential execution, not corruption. `enqueue` needs
no special handling anymore — a pending run simply isn't claimable until its thread frees up
(see claim query), so `_handle_contention` and the enqueue-requeue loop are **deleted**.

### Dispatch (`RunDispatcher`)

BRPOP is replaced by the trigger-scanner pattern — poll every `RUN_CLAIM_INTERVAL` (~0.5s):

```sql
UPDATE runs SET status = 'running', updated_at = now()
WHERE id IN (
  SELECT p.id FROM runs p
  WHERE p.status = 'pending'
    AND NOT EXISTS (SELECT 1 FROM runs r
                    WHERE r.thread_id = p.thread_id AND r.status = 'running')
  ORDER BY p.created_at
  LIMIT :free_slots
  FOR UPDATE SKIP LOCKED
)
RETURNING id;
```

Claim = atomic `pending → running` across all instances; the semaphore cap per process stays.
Added dispatch latency (≤ poll interval) is invisible next to multi-second agent turns.

### Liveness + reaper

Worker stamps `SET run:{id}:alive "1" EX <heartbeat_timeout>` every
`heartbeat_interval_seconds`. Reaper worklist flips to SQL: for each `status='running'` row,
if the Redis alive key is gone → finalize `error` ("Worker stopped responding"). Pending
zombies: `status='pending' AND created_at < now() - pending_timeout AND` thread has no running
run → finalize `error`. Reaper stays in-process (same Cloud Run scale-to-zero caveat as today:
a fully idle service reaps late, on next boot — unchanged behavior, external cron later if it
ever matters).

### Cancel

Running run: Redis control channel, unchanged. Pending run: guarded
`UPDATE ... SET status='cancelled' WHERE id=:id AND status='pending'`.

### Finalize — now one transaction

`RunService.finalize(run_id, status, error=None)`:

1. **One DB transaction**: guarded terminal update
   (`UPDATE runs SET status, error WHERE id=:id AND status NOT IN (<terminal>)` — idempotent,
   worker and reaper may both call) **plus** `UPDATE threads SET last_run_status=:status` on
   the same connection. The run outcome and the thread stamp can no longer disagree — the
   best-effort gap from the column-only plan is gone.
2. Then Redis: publish the `end` sentinel, TTL the events/control keys (1h, as today).

All terminal statuses stamp the thread, including `interrupted` (doubles as a
"waiting for approval" badge) and `cancelled` (truthful; frontend doesn't style it as
failure). The old exclusion for contention-rejects is moot — that path no longer exists.

### Reattaching to an old run

New edge the durable record creates: `GET /{run_id}/stream` on a run whose events have
TTL'd away (>1h) would block forever waiting for a sentinel on an empty stream. Fix in
`RunService.stream`: if the run is terminal in Postgres and the events key doesn't exist,
emit a synthetic `end` sentinel immediately.

## API surface (endpoints unchanged, semantics upgraded)

- `GET /threads/{id}/runs` — full durable history, newest first (consider a `limit` param;
  it's unbounded now).
- `GET /runs/active` — one indexed SQL query instead of Redis scatter-gather.
- `POST /stream`, `POST /invoke`, `POST /{run_id}/cancel`, reattach — unchanged contracts.
- `ThreadResponse` += `last_run_status: str | None`; flows through existing projections.

## Frontend

- `Thread` type += `lastRunStatus` (axios camelizes).
- Sidebar/thread list: failure badge when `lastRunStatus ∈ {error, timeout}` and the thread is
  not in the active-runs store (busy is *derived* from the existing `/runs/active` poll —
  never stored, per the LangGraph `ThreadStatus` discussion).
- Trigger run-history view: per-firing status from each thread's `last_run_status` (trigger
  threads are 1:1 with firings), with full run rows available for detail later.

## Retention

- `RUN_RETENTION_DAYS` (default 90) in `RunSettings`. Daily sweep (piggybacked on the reaper
  loop): `DELETE FROM runs WHERE status IN (<terminal>) AND created_at < now() - interval`.
  Never deletes non-terminal rows. Safe by construction: `threads.last_run_status` is
  denormalized, so pruning never breaks the badge.
- Optional later: two-tier retention (NULL out `input`/`command`/`config_overrides` after
  ~30 days, keep the ~200-byte skeleton row forever).
- Volume for context: ~2 KB/run ⇒ even 1k runs/day is <1 GB/year, a rounding error next to
  LangGraph checkpoint storage.

## Module reshape (file by file)

| File | Change |
| --- | --- |
| `runs/models.py` | **new** — `RunDB` |
| `runs/repository.py` | **new** — `RunRepository`: `create`, `get`, `list_for_thread`, `claim_pending(limit)`, `finalize_run(id, status, error)` (guarded terminal UPDATE + thread stamp), `list_active_for_user`, `list_running`, `cancel_pending`, `prune_terminal` |
| `runs/state.py` | keep `RunStatus`, `TERMINAL_STATUSES`, `transition`; drop `RunRecord`/`to_redis`/`from_redis` |
| `runs/registry.py` | **deleted** → replaced by repository + `runs/liveness.py` (Redis alive key: `stamp`, `is_alive`) |
| `runs/queue.py` | **deleted** — claim lives in the repository |
| `runs/keys.py` | drop record/index/mutex keys; keep events + control, add alive |
| `runs/service.py` | same public verbs; opens short `AsyncSessionLocal()` sessions internally (it already lives outside `get_db` — worker, reaper, Slack, triggers all construct it without a request; the router keeps injecting it as today) |
| `runs/worker.py` | drop `claim_active`/`_handle_contention`; heartbeat → alive key; `_execute`/`_stream` unchanged shape |
| `runs/reaper.py` | SQL worklist + Redis alive check + daily prune pass |
| `runs/router.py` | unchanged surface; expired-events sentinel case |
| `runs/schemas.py` | `RunResponse.from_record` → from `RunDB` |
| `threads/models.py` + `threads/schemas.py` | `last_run_status` column + response field |
| `alembic/` | one hand-written revision (runs table + threads column) |
| Slack `handlers.py`, `triggers/service.py`, `main.py` lifespan | **no changes** — call sites keep the same `RunService` API |

Tests: `test_registry.py`/`test_queue.py` → `test_repository.py` (claim ordering, mutex via
unique index, reject race, guarded finalize idempotence, prune); `test_worker.py` reworked
(no contention path, alive-key heartbeat); add: finalize stamps `threads.last_run_status` in
the same transaction; reattach-to-expired-events yields synthetic end; `test_state.py`,
`test_events.py`, `test_control.py` unchanged.

## Rollout

1. Ship migration + code together; no backfill, no data migration.
2. In-flight runs at deploy time: same story as any deploy today — the dispatcher drains on
   shutdown, stragglers are reaped on the next boot. Old-format Redis record keys expire on
   their own within an hour.
3. No frontend coordination needed: SSE wire shape, headers, and endpoints are byte-identical.

## Accepted tradeoffs

- Dispatch latency ≤ claim poll interval (vs BRPOP's ~0) — irrelevant at agent-turn timescales.
- Event-log replay window stays 1h (Redis TTL) — durable history is the *record* (status,
  params, error), not the token stream. Reattach after 1h returns just the end state.
- Reaper remains in-process; a fully scaled-to-zero service stamps dead runs late (unchanged
  from today).
- Semantic failures still finalize as `success` by design (`GraphRecursionError` fallback,
  middleware-repaired tool errors) — `last_run_status='error'` means root-level run failure,
  which is exactly what the badge should mean.
