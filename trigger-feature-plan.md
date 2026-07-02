# Triggers — design & implementation notes

A **trigger** is a named, scheduled instruction assigned to exactly one agent and owned by a
user. On each occurrence it creates a fresh thread + a background run on the durable runtime —
the same substrate web `/runs/stream`, `/runs/invoke` and Slack turns already use. Triggers get
their own entrypoint alongside Agents, MCP servers and Users, with pause/unpause, and only
workspace **editors** can create them.

This doc is both the design rationale and the map of the implementation (`backend/app/triggers/`).

---

## 1. The scheduling question: how do we know when the next runs are?

This was the open architectural question, so it gets the deep dive. Three candidate models:

### Option A — derive due-ness from the last run (rejected)

"The cron scans the previous triggered run and sees if the next has been run." Every tick, for
every active trigger: parse its cron, compute the occurrence after `last_run_at`, compare to
now.

- **Unindexable.** Due-ness is the output of cron math, not a column — the scanner must load
  *every* active trigger *every* tick and evaluate croniter per row. Fine at 10 triggers,
  quadratically annoying later.
- **Racy across instances.** Cloud Run runs several instances; each one derives the same
  "trigger X is due" conclusion independently. You then need a separate claim mechanism anyway
  to avoid double-firing — so you end up building Option B's locking without its index.
- **Ambiguous after edits.** Change the cron from daily to hourly: is the trigger immediately
  due because `last_run_at` predates several hourly occurrences? Every edit needs bespoke
  "what does the past mean now" logic.

### Option B — persist exactly one `next_run_at` per trigger (chosen)

Materialize the *single next occurrence* as a UTC timestamp column, maintained at every write:

- **create** (active) → `next_run_at = compute_next_run_at(cron, tz, after=now)`
- **pause** → `next_run_at = NULL` (the row physically leaves the partial index — a paused
  trigger costs nothing at scan time)
- **unpause / schedule edit** → recompute from *now*
- **fire** → advance to the following occurrence before enqueueing

The scanner's question "what is due?" becomes one indexed query:

```sql
SELECT * FROM triggers
WHERE is_active AND next_run_at IS NOT NULL AND next_run_at <= now()
ORDER BY next_run_at LIMIT :batch
FOR UPDATE SKIP LOCKED
```

`FOR UPDATE SKIP LOCKED` is what makes multi-instance safe *without leader election*: when
several instances tick concurrently, each locks a disjoint subset of due rows; a row claimed by
one tick is invisible to the others. The claim completes when the claimer advances
`next_run_at` and commits. This is the same "every instance runs the loop, Postgres arbitrates"
style as the run reaper.

### Option C — pre-materialize N future occurrences as rows (rejected for now)

A `trigger_occurrences` table with the next N planned firings (what many job schedulers do).
Buys per-occurrence audit rows and an "upcoming runs" list straight from the DB — but costs a
planner (top-up job), re-planning on every schedule edit, and GC. None of that is needed:

- **Audit of past firings** already exists — each firing creates a thread with
  `threads.trigger_id` set, and the run's status lives in the runtime's `RunRecord`.
- **Upcoming occurrences for the UI** don't need persistence at all: they're a pure function of
  `(cron, tz, now)`. `GET /triggers/schedule/preview?cron_expression=...&timezone=...&count=5`
  computes them on demand (`app/triggers/schedule.py::list_next_run_ats`). The backend plans
  **exactly one** run ahead per trigger; the UI can *display* as many future occurrences as it
  likes for free.

### So, concretely

- **How many next runs does the backend plan?** One per trigger — the `next_run_at` column.
- **Are next runs persisted?** Only that one; future occurrences are computed, past occurrences
  are the trigger's threads.
- **Does anything scan previous runs?** No. The scanner never looks backward; `last_run_at` is
  observability only.

### Missed occurrences are skipped, not replayed

If the worker was down (or a trigger paused) across occurrences, the recompute is always
`after=now`: a daily 08:00 trigger that couldn't fire Monday does **not** fire twice Tuesday.
For scheduled agent prompts ("post the daily digest") catch-up runs are noise, and skipping
makes every failure mode safe — see the crash analysis below. The trade-off is deliberate and
should stay documented in the UI copy ("missed runs are skipped").

### Crash safety: advance-then-enqueue

The claim (Postgres) and the enqueue (Redis run queue) cannot be one transaction. Order matters:

1. Claim rows (locked), advance `next_run_at`, stamp `last_run_at`, create the threads.
2. `COMMIT` — the occurrence is now consumed, locks released.
3. Enqueue one run per created thread onto the run queue.

A crash between 2 and 3 **skips** that occurrence (thread exists, no run — visible, harmless).
The reverse order would double-run on crash, which is worse for a scheduled message. Enqueue
failures are caught per-trigger and logged; the next occurrence is unaffected.

### Schedule storage: `cron_expression` + `timezone`

The canonical schedule is a cron string plus an IANA timezone, validated with `croniter` +
`zoneinfo` (`app/triggers/schedule.py`). Why not a structured `{frequency, time, days}` JSONB?

- Cron is the lingua franca: any preset the UI offers ("every day at 8am" → `0 8 * * *`)
  lowers to it deterministically, and power users can type it raw.
- The timezone must be first-class either way — "8am" is meaningless without one, and the cron
  is evaluated *in that zone* (DST handled by croniter over aware datetimes), then normalized
  to UTC for storage/comparison.
- Presets are a frontend concern. The UI maps preset ↔ cron for the common shapes and shows the
  preview endpoint's output as ground truth; the backend never sees preset vocabulary.

`next_run_at` is always computed strictly *after* the reference instant, so a fire at exactly
08:00:00 schedules 08:00 tomorrow, not itself.

---

## 2. How a trigger fires (end to end)

The durable runtime (`app/agents/runs/`, formerly PR #89) is **merged** — dispatcher and reaper
already boot in `lifespan`, Slack runs ride it. Triggers add one sibling loop and nothing else:

```
TriggerScanner (app/triggers/scanner.py, every TRIGGER_SCAN_INTERVAL_SECONDS=20s)
  └─ TriggerService.claim_and_enqueue(now)          # own AsyncSessionLocal, own commit
       ├─ repo.claim_due(now)                       # FOR UPDATE SKIP LOCKED
       ├─ per trigger: advance next_run_at, stamp last_run_at,
       │   ThreadService.create(source=trigger, trigger_id=...)   # fresh thread per fire
       ├─ COMMIT                                    # occurrence consumed
       └─ RunService.create(thread_id, user_id=owner,
            input={"messages":[{"type":"human","content": instructions}]})
                 ↓
RunDispatcher (existing) BRPOPs the queue on any instance
  └─ RunWorker → Agent.build(thread, db) → agent.stream(...) → event log / checkpoint
```

Everything downstream of `RunService.create` is untouched, so triggered runs inherit
durability, server-side cancel, reattach (open the thread and watch the 08:00 run still
streaming), heartbeats, and reaper recovery for free.

- **Scanner placement**: booted in `lifespan` only where the dispatcher runs
  (`RUN_DISPATCHER_ENABLED` instances — always-on, CPU-unthrottled). `TRIGGER_SCANNER_ENABLED=false`
  turns it off independently. Latency bound = scan interval (20s), fine for minute-granularity cron.
- **The owner's credentials fall out for free**: the run thread's `user_id` is the trigger
  owner, `Agent.build` derives MCP token storage from `thread.user_id`, so triggered runs use
  the owner's OAuth vault with zero extra plumbing.
- **One thread per fire** (`ThreadSource.trigger`, included in `FIRST_PARTY_SOURCES` — the
  owner sees each firing in their personal sidebar list, badged via `source`/`trigger_id`).
  `threads.trigger_id` links each firing back to its trigger for a per-trigger history view;
  `ondelete=SET NULL` keeps history when a trigger is deleted.
- **Run status lives on the run, not the trigger.** The trigger row carries scheduling state
  only (`next_run_at`, `last_run_at`). "Did the 08:00 run fail?" is answered by the linked
  thread's `RunRecord` — duplicating a `last_status` column would re-implement the run state
  machine. Note Redis run retention is short (1h default), so a history UI should treat run
  records as recent-status-only and rely on the thread's checkpoint for the transcript.
- **Naming collision, noted**: `RunRecord.trigger` (an AI SDK stream field, e.g.
  `"submit-message"`) predates this feature and is unrelated to trigger entities. Triggered
  runs leave it `None`. If it ever confuses, rename that field to `stream_trigger` — don't
  overload it with a trigger id.

### Self-disabling triggers

`claim_and_enqueue` pauses (rather than fires) a claimed trigger whose agent is archived/gone
or whose schedule no longer computes — a poison row must not wedge or spam the scan loop. The
pause is visible in the UI (`is_active=false`), which doubles as the notification.

---

## 3. Data model (as built)

`app/triggers/models.py` — `TriggerDB`, table `triggers`, inherits `BaseDBModel`:

| Field | Type | Notes |
| --- | --- | --- |
| `name` | `str(255)` | human label; also used as the thread title for firings |
| `instructions` | `Text` | the scheduled prompt, sent verbatim as the human message |
| `owner_id` | UUID FK `users.id`, CASCADE | runs execute as this user (vault + permissions) |
| `agent_id` | UUID FK `agents.id`, CASCADE | the assigned agent |
| `model_id` | `str(255)` | validated against the `MODELS` catalog (runtime requires one) |
| `cron_expression` | `str(255)` | validated by croniter |
| `timezone` | `str(64)`, default `UTC` | IANA zone the cron is evaluated in |
| `is_active` | `bool`, default true | pause/unpause |
| `next_run_at` | timestamptz, nullable | **the** scheduler state; NULL while paused |
| `last_run_at` | timestamptz, nullable | observability only |

Indexes: `owner_id`, `agent_id`, and the scanner's hot partial index
`ix_triggers_due ON (next_run_at) WHERE is_active AND next_run_at IS NOT NULL` (declared in
`__table_args__` and in the migration).

Migration `b6d1c8e4f2a7_add_triggers.py` (upgrade/downgrade round-trip verified): creates
`triggers`, adds `threads.trigger_id` (nullable FK, SET NULL, indexed). `ThreadSource.trigger`
is Python-only (the column is `String`) — no enum migration. New dependency: `croniter`.

Schemas (`app/triggers/schemas.py`): `TriggerBase` / `TriggerCreate` / `TriggerCreateDB`
(+`owner_id`, +`next_run_at`) / `TriggerPatch` / `TriggerResponse` / `SchedulePreviewResponse`.

---

## 4. API surface (`/triggers`)

| Endpoint | Auth | Behavior |
| --- | --- | --- |
| `GET /triggers/` | any user | admin → all; otherwise own triggers |
| `POST /triggers/` | **`require_editor`** | validates schedule + model + agent-usable-by-owner; computes `next_run_at` |
| `GET /triggers/schedule/preview` | any user | next N occurrences of `(cron, tz)` — pure computation, powers the schedule designer |
| `GET /triggers/{id}` | owner or admin | |
| `PATCH /triggers/{id}` | owner or admin | pause/unpause via `is_active`; schedule edits recompute `next_run_at`; agent change re-checked against the **owner's** permission |
| `DELETE /triggers/{id}` | owner or admin | hard delete; past threads survive (SET NULL) |

Permission notes:

- "Selectable agents" = agents where the **owner's** `current_user_permission` is not `None` —
  enforced by `TriggerService._ensure_agent_usable` on create and on agent change (checked
  against the owner even when an admin edits), and surfaced in the UI by the existing
  `GET /agents` list.
- Only workspace editors+ can *create*; management of an existing trigger is owner-or-admin. A
  later role downgrade doesn't strand the owner's triggers (they can still pause/delete).

---

## 5. Repository & service (as built)

`TriggerRepository` (`repository.py`): `list_all`, `list_for_owner`, and `claim_due(now, limit)`
— the locked due-scan described in §1.

`TriggerService` (`service.py`): CRUD with the guards above, plus the scanner entrypoint
`claim_and_enqueue(now) -> list[run_id]`, which owns the claim → thread → commit → enqueue
choreography. It commits its own session and therefore **must never be called inside a
request-scoped transaction** — only from the scanner (or a test) over a dedicated
`AsyncSessionLocal()`, the same out-of-request pattern as Slack handlers.

Pure schedule math lives out of the service in `schedule.py` (`ensure_valid_schedule`,
`compute_next_run_at`, `list_next_run_ats`), per the "pure helpers stay out of services" rule.
Tunables in `settings.py` (`TRIGGER_SCANNER_ENABLED`, `TRIGGER_SCAN_INTERVAL_SECONDS=20`,
`TRIGGER_CLAIM_BATCH_SIZE=50`).

---

## 6. Not built yet / open decisions

1. **Frontend** — sidebar entry + `/triggers` page (list with pause toggle + next/last run),
   create/edit form (agent picker filtered by permission, model picker, schedule designer with
   preset → cron mapping and the preview endpoint), and a per-trigger run-history view over
   threads with `trigger_id = X` (needs a small `list_for_trigger` read path when built).
2. **HITL on triggered runs.** No human is present at fire time: if the agent has
   `needs_approval` tools, the run finalizes as `interrupted` and parks. Because trigger
   threads are first-party (sidebar-visible) and owned by the trigger owner, the *resolution
   path already works*: opening the thread shows the pending approval and approving resumes it
   through the normal web flow (a new run with a resume command), exactly like an interrupted
   web thread. What's still open is only *awareness* — an interrupted run sits silently until
   the owner opens the thread. Options: an "awaiting approval" badge on the sidebar/trigger
   list, or a Slack notification after a firing interrupts.
3. **Owner permission revocation.** The scanner pauses triggers whose *agent* is archived, but
   a revoked per-agent grant currently surfaces as run failures instead of a pause. A readiness
   check in `claim_and_enqueue` (resolve owner permission before firing) would close this; it
   costs one permission query per firing.
4. **Failure notifications.** A trigger whose runs consistently error is only visible by
   opening its threads. Consider surfacing last-run status in the list view (join the latest
   trigger thread → run record) or notifying via Slack after N consecutive failures.
5. **Model deprecation.** `model_id` is validated at write time; if a model later leaves the
   catalog, runs start failing at build time ("Unknown model"). Same self-pause treatment as
   archived agents would fit if it becomes a real problem.
