# HITL durability: where approval state actually lives, and what LangGraph 1.x now gives us

Written 2026-08-31, against the versions installed today: `langgraph 1.2.11`,
`langgraph-checkpoint 4.2.0`, `langgraph-checkpoint-postgres 3.0.4`,
`langchain 1.3.17`, `langgraph-sdk 0.4.3`.

## TL;DR

**No pending approval is in Redis today, and none should ever be.** The interrupt
is already in the LangGraph **Postgres** checkpoint, which has no TTL in the OSS
saver. P3-6's "machine-readable HITL block id" is about the *Slack message's*
`block_id` — Slack's message store, not Redis. So the durability the ticket asks
for already exists; what is missing is a **stable id** to key it by, and LangGraph
1.x now ships one (`Interrupt.id`) plus a resume form that uses it
(`Command(resume={id: value})`).

## 1. What auxilia stores where (verified)

| Thing | Store | TTL |
| --- | --- | --- |
| The interrupt itself (`__interrupt__` pending write) | Postgres, LangGraph checkpoint | **none** |
| Run record incl. the replay `command` (`{"resume": {...}}`) | Postgres, `runs` table | pruned after `RUN_RETENTION_DAYS` |
| `threads.last_run_status` (can be `interrupted`) | Postgres | none |
| Slack approval decision | the Slack message blocks themselves | none |
| SSE event log / cancel signal / worker liveness | Redis | yes — but these are a *replay window*, not a record |

`runs/SPEC.md` already states the invariant: "Durable conversation state stays in
the LangGraph Postgres checkpoint (keyed by `thread_id`); the run is the execution
envelope around producing the next checkpoint." A run being `interrupted` is
terminal *for that run*; resuming creates a new run. Nothing about that path
expires.

Read path today: `ThreadRepository`/`threads/router.py:92` and
`slack/consumer.py:189` both go through `pending_interrupt()` /
`pending_approval_requests()` in `app/threads/serialization.py`, which scan the
checkpoint tuple's `pending_writes` for the `__interrupt__` channel. That is a
checkpoint read — correct by construction, and it is why an approval can be picked
up days later.

`langgraph-checkpoint-postgres` 3.0.4 has **no** TTL/sweep code at all (grepped:
the whole `langgraph/checkpoint/` tree has no `ttl`). Checkpoints live until we
delete them, which we do explicitly on thread delete and permanent agent delete.
So "pending forever" is the current, intended behaviour — expiry, if we ever want
it, is our own sweep on our own table, never a store-level TTL.

## 2. What changed in LangGraph that we are not using

### 2.1 `Interrupt.id` — the machine-readable id we were about to invent

`langgraph/types.py:575` — `Interrupt` is now `(value, id)`. The id is
`xxh3_128_hexdigest` of the interrupting task's checkpoint namespace, so it is
**deterministic and derived from the checkpoint** — nothing to store, stable
across restarts, and it changes when the thread moves on.

History: `interrupt_id` appeared as a property in 0.4.0; in 0.6.0 the class was
slimmed to `value` + `id` and `ns` / `when` / `resumable` / `interrupt_id` were
removed. We are on 1.2.11, so we have the final shape.

`app/threads/serialization.py:116` currently does
`return getattr(first, "value", first)` — i.e. it reads the `Interrupt` object out
of the pending write and **throws the id away**. Keeping it is a one-line change
and it is exactly the identifier P3-6 wants for the Slack `block_id`.

### 2.2 `Command(resume={interrupt_id: value})`

`langgraph/pregel/_loop.py:910` — if `resume` is a dict whose keys are *all*
xxh3-128 hexdigests, it is treated as a resume **map** keyed by interrupt id
(otherwise it's a plain resume value, so there is no ambiguity with our
`{"decisions": [...]}` payload).

Two consequences for us:

- **Stale-decision safety.** Today `_resolve_input` (`runtime.py:491`) sends
  `Command(resume=command["resume"])` blind: whatever interrupt is pending gets
  the decisions. If someone approves in the web UI and then a stale Slack button
  is clicked (or a queued Slack retry lands), the second resume applies to
  *whatever the thread is paused on now*. Keying by interrupt id makes that a
  no-op we can detect and report instead of a mis-approval.
- **Multiple pending interrupts now raise.** `_loop.py:917`: with more than one
  hanging interrupt and a non-map resume, LangGraph raises
  `RuntimeError("When there are multiple pending interrupts, you must specify the
  interrupt id when resuming")`. We don't hit it today — `HumanInTheLoopMiddleware`
  raises one interrupt per model turn carrying the whole batch in
  `action_requests` — but parallel subagents each pausing for approval would.

### 2.3 `StateSnapshot.interrupts`

`langgraph/types.py:700` — `StateSnapshot` now exposes
`interrupts: tuple[Interrupt, ...]`, the supported read API. It requires a
compiled graph (`aget_state`), which on our side means an `Agent.build`; our
`checkpointer.aget_tuple` + `pending_writes` scan is cheaper and stays the right
call for the thread-read and worker paths. We just need to stop discarding `.id`.

### 2.4 Decisions are still positional

`langchain/agents/middleware/human_in_the_loop.py` — `HITLRequest.action_requests`
carries only `name`/`args` (no id) and `HITLResponse.decisions` is a positional
list. So `pending_approval_requests()`'s name+args re-matching to recover a
`tool_call_id` is still necessary. That is fine: both the request order and the
tool calls come from **the same checkpoint read**, so the mapping is
reproducible — as long as we never persist the position anywhere and re-derive it
at resume time. (We don't.)

## 3. How LangGraph Platform handles it

Same substrate, plus one denormalization:

- The interrupt lives in the Postgres checkpoint, exactly as ours does.
- The **thread row** carries `status: "idle" | "busy" | "interrupted" | "error"`
  and `interrupts: dict[task_id, list[Interrupt]]` (`langgraph_sdk/schema.py:311`),
  written when a run ends. That is what makes "list everything awaiting approval"
  one indexed query instead of N checkpoint reads — you can `threads.search` by
  `status="interrupted"`.
- Resuming is a **new run** on the thread with `Command(resume=...)` — identical
  to our model (`RunStatus.interrupted` is terminal for the run; the Slack path
  already creates a new run at `slack/handlers.py:455`).
- Expiry is **opt-in**: `checkpointer.ttl` in `langgraph.json`, strategy `delete`
  (thread + runs + checkpoints) or `keep_latest`, swept every 5 min, **default
  none — threads never expire**. Platform does not special-case interrupted
  threads, which is another reason its default is "no TTL".

We already have Platform's shape: `threads.last_run_status` is their `status`
column, and `interrupted` is one of its values.

## 4. Recommendation for P3-6

Source of truth stays the checkpoint. Three small changes:

1. **Stop discarding `Interrupt.id`.** `pending_interrupt()` returns
   `(id, value)`; `pending_approval_requests()` stamps `interrupt_id` on every
   request it returns. Nothing new is stored — the id is a pure function of the
   checkpoint.
2. **Slack `block_id = f"hitl:{interrupt_id}:{index}"`**, emoji demoted to
   presentation. Batch reconstruction reads ids instead of `:white_check_mark:`
   strings, and a stale batch becomes detectable: if the thread's pending
   interrupt id no longer matches the one in the block, the decision was already
   made — post "already handled" instead of resuming the wrong turn.
3. **Resume with the map form**: `Command(resume={interrupt_id: {"decisions":
   [...]}})` in `_resolve_input`, keeping the bare form as the fallback for runs
   created before the id is present. This is also what unblocks per-subagent
   approvals later.

A "pending approvals" inbox is **not optional** — it is the trigger-HITL feature
(see step 7 below): index `threads.last_run_status` (Platform's move) rather than
adding a new table. No TTL, no sweep — a pending approval that is never answered
stays answerable, and if we later decide stale requests should lapse, that is a
status transition we own, not a key that vanished.

---

# The P3-6 HITL plan, keyed on `Interrupt.id`

Scope note: P3-6 as filed bundles three things — typed event envelopes, the
`error_code` column, and the HITL block id. Only the third is below; the first two
are unaffected by any of this.

## Why the id changes the shape of the fix

The original suggestion ("put the decision in a machine-readable `block_id`, keep
emoji as presentation") fixes exactly one failure: a copy tweak to the status
emoji breaking `_extract_decision`. Everything else about the approval path stays
as fragile as it is today, because the *identity* of the batch is still inferred:

- `_get_latest_approval_batch` (`slack/handlers.py`) guesses the batch as "the
  trailing run of contiguous approval-looking messages".
- The decision list is **positional** in both clients — the web hook orders by
  `pendingToolCalls`, Slack by message order — and the backend passes it straight
  through to `Command(resume=…)` (`runtime.py:491`).
- A stale click (approved in the web UI first, or a Slack retry) resumes
  **whatever the thread is paused on now**. No check exists.

`Interrupt.id` replaces all three inferences with one identifier that we don't
own and can't drift: it is a hash of the interrupting task's namespace, recomputed
from the checkpoint on every read.

## Steps

### 1. Stop discarding the id (`app/agents/hitl.py`, new leaf module)

Move `pending_interrupt` / `pending_approval_requests` out of
`app/threads/serialization.py` into a new `app/agents/hitl.py` and have them keep
the id:

```python
class PendingInterrupt(NamedTuple):
    id: str
    value: Any

def pending_interrupt(checkpoint_tuple) -> PendingInterrupt | None
def pending_approval_requests(cp) -> list[ApprovalRequest]  # + interrupt_id
def build_resume_command(requests, decisions: dict[str, Decision], interrupt_id) -> dict
```

The move also fixes a layering wrinkle: `agents/runs/worker.py:32` currently
imports the run runtime's terminal-status detection from `app.threads`. Three
call sites to update (`threads/router.py:92`, `runs/worker.py:247`,
`slack/consumer.py:189`). CLAUDE.md lists `agents/hitl.py` as a ghost file removed
in P0-5 — that line becomes true again and needs updating.

### 2. Put the id on both read paths

- `GET /threads/{id}` returns `interrupt_id` beside `interrupt_value` (this is the
  rehydrate path the web UI uses after a reload).
- The live SSE already carries it: `stream.py:104` does
  `dataclasses.asdict(Interrupt)`, and `Interrupt` is a `@dataclass(slots=True)`
  with `value` **and** `id` — verified. No backend change for the streaming path;
  the web client just has to read `interrupt.id`.

### 3. Canonicalize the resume at the boundary (`RunService.create`)

Clients stop sending a positional list. New command shape:

```json
{"interrupt_id": "<32 hex>", "decisions": {"<tool_call_id>": {"type": "approve"}}}
```

`RunService.create` reads the checkpoint once (it is a resume, so this is a rare
path), and:

- **rejects a stale resume** — no pending interrupt, or a different id → 409
  `StaleApprovalError` (body `{"error": "stale_interrupt"}`; a dedicated
  exception, since `DomainValidationError` is a 400 and the client must tell
  this apart from `model_unavailable`, the other 409 on this path);
- **orders the decisions itself**, against `action_requests` from the checkpoint,
  because `HITLResponse.decisions` is still positional in
  `langchain/agents/middleware/human_in_the_loop.py` and always will be;
- **stores the canonical form** in `RunDB.command`:
  `{"resume": {"<interrupt_id>": {"decisions": [...]}}}`, so replay of a stored
  run is byte-exact and the worker and `runtime._resolve_input` stay unchanged —
  LangGraph auto-detects the map form (`pregel/_loop.py:910`).

Keep accepting the legacy positional shape for one release: `RunDB` rows created
before the deploy carry it, and replay must not break.

Why the explicit 409 rather than leaning on LangGraph: a resume map whose id
matches nothing is *safe* (the node re-runs and interrupts again, no tool fires)
but **silent** — the run just ends `interrupted` again and the user sees nothing.

### 4. Slack: `block_id`, and delete the contiguity heuristic

- `build_tool_approval_blocks` sets `block_id=f"hitl:{interrupt_id}:{tool_call_id}"`
  on the actions block.
- `_update_approval_message` swaps in the context block carrying
  `block_id=f"hitl:{interrupt_id}:{tool_call_id}:{decision}"`. The emoji stays,
  as presentation only.
- `_collect_batch_decisions` reads block ids: the batch is every card whose
  `interrupt_id` matches the one currently pending on the thread, and it is
  complete when the decided `tool_call_id`s cover `pending_approval_requests()`.
  `_get_latest_approval_batch`, `_is_approval_message` and the emoji branches of
  `_extract_decision` all go away — the batch is *identified*, not guessed, so an
  interleaved message (a failure notice, a "View in auxilia" link) can no longer
  truncate it.
- A click on a card from an already-resolved interrupt hits the step-3 409 and
  posts "already handled" instead of resuming the wrong turn.

`block_id` has a 255-char budget; `hitl:` + 32 + a tool-call id + a decision is
well inside it, and it only has to be unique within its own message.

### 5. Web: `use-hitl-approvals.ts`

Submit `{interrupt_id, decisions: {toolCallId: {type}}}` instead of the positional
`ordered` array, and key `submittedForBatchRef` on the interrupt id rather than a
joined list of tool-call ids — which is what that ref was approximating anyway.

### 5b. What the frontend does and doesn't hold (why step 5 matters)

The web client stores **nothing** for HITL, correctly: `decisions` and the
submit-dedup ref in `use-hitl-approvals.ts` are in-memory, and losing them on
refresh is the right semantics — the checkpoint either still pends (re-render,
re-decide) or doesn't (done). Durability was never the frontend's problem.

What the id adds on the web is correctness in two places:

- **Stale view.** The multitask `reject` gate covers a second submit only while
  the resume run is in flight. After it completes and the agent interrupts on a
  *new* batch, an unrefreshed tab / Slack card / inbox row submits old positional
  decisions that land on the new `action_requests`. The id turns that into the
  step-3 409. The step-7 inbox multiplies the surfaces showing one pending
  approval, so steps 3 and 7 ship together.
- **An unchecked ordering invariant, deleted.** Today's positional submit works
  because three codebases happen to agree on order: the middleware builds
  `action_requests` in the last AI message's tool-call order, `page.tsx:720`
  renders `pendingToolCalls` in that same order (a *name-set* filter over
  message-ordered tool calls), and the backend passes the array through. Nothing
  checks this. Sorting or grouping the approval cards in the UI would silently
  misassign decisions — and execute the wrong tool. Keying by `tool_call_id`
  with server-side ordering (step 3) removes the invariant from the client.

The single-tab fresh-interrupt path is correct today and gains nothing — the id
is insurance on every other path.

### 6. Tests

Id survives the checkpoint read; stale resume → 409; Slack post → update →
collect round-trip through block ids; decision order comes from the checkpoint and
not from client order (feed them reversed); a legacy positional command still
resumes.

## Is it better than the original suggestion?

Yes, and it is not more work — it is the same edit surface with a better key:

| | original (`block_id` carries the decision) | keyed on `Interrupt.id` |
| --- | --- | --- |
| id origin | invented by us | derived from the checkpoint, recomputed on read |
| batch identity | still "trailing contiguous messages" | the interrupt id |
| decision order | positional, set by each client | server-side, from `action_requests` |
| stale click | resumes whatever is paused now | 409, told to the user |
| parallel interrupts (subagent HITL) | `RuntimeError` at `_loop.py:917` | supported |
| new state stored | none | none |

The costs are real but small: one checkpoint read per resume-run creation, a
payload change in two clients (hence the one-release legacy fallback), and a
migration-free but cross-surface change that has to ship backend-first.

One thing to verify when subagent HITL lands: an interrupt raised inside a
subgraph task has that task's namespace hash as its id. Our readers all take the
root thread's checkpoint tuple today, which is where the propagated interrupt
write lands — worth an explicit test rather than an assumption.

---

# Review against the actual goals (2026-08-31)

The requirement, stated precisely: *the LangGraph checkpoint is the source of
truth for "this thread is waiting on HITL"* — so a page refresh always shows the
pending actions, a Slack card is approvable days later, and a user can list every
trigger waiting on them.

**Goal 1 — refresh always shows the HITL actions: already true today.**
`GET /threads/{id}` (`threads/router.py:92`) reads `pending_interrupt` from the
checkpoint tuple and returns `interrupted` + `interrupt_value`; the chat page
rehydrates from it (`page.tsx:825`). Postgres checkpoint, no TTL, nothing to fix.
The plan only adds `interrupt_id` to the payload (step 2).

**Goal 2 — Slack approval days later: durable today, correct only with the plan.**
The checkpoint and the Slack messages both persist; the click path never touches
Redis. But at day 3 the *batch* is guessed by message adjacency and the resume is
blind — a click after someone already approved from the web resumes whatever the
thread is paused on now. Steps 3–4 (id in `block_id`, 409 stale-guard) are what
make the late click safe: it either resumes the right turn or reports "already
handled".

**Goal 3 — list all triggers waiting on my approval: the missing piece.**
Verified: trigger threads are owned by the trigger owner
(`claim_and_enqueue` → `user_id=trigger.owner_id`, `source=trigger`,
`trigger_id` FK, `triggers/service.py:255–266`), and trigger runs ride the same
worker, so a HITL tool in a trigger run *already* finalizes the run as
`interrupted` with the request in the checkpoint — no new runtime work. What is
missing is the query: you cannot scan N checkpoints to build an inbox. The
denormalized column already exists (`threads.last_run_status`, stamped in the
same transaction as the run's terminal update — `runs/service.py:312`) but is
**unindexed** (`threads/models.py:69`). Step 7 below turns it into the inbox.
This was filed above as "optional" — wrong lens; for triggers it is the feature.

### 7. Approvals inbox (the trigger-HITL surface)

- **Migration**: partial index on `threads(user_id)` where
  `last_run_status = 'interrupted'` — `interrupted` is a rare value, so the
  partial index stays tiny and the hot write path (stamping terminal statuses)
  barely notices it.
- **Endpoint**: `GET /approvals` (or `GET /threads?awaiting_approval=true`) —
  threads where `user_id = me AND last_run_status = 'interrupted'`, optional
  `source=trigger` filter, joined with `trigger_id` → trigger name for the
  trigger view. For each row (bounded page), one `pending_approval_requests()`
  checkpoint read supplies the actual actions — and doubles as the truth check:
  a thread whose resume run is already in flight (the stamp lags until that run
  finalizes) reads back `[]` and is dropped from the response. The column is the
  *index into* the checkpoint, never the truth.
- **Approving from the inbox** is the existing web resume path — open the thread,
  the step-1/2 payload renders the actions, the step-3 canonical command resumes
  it. Nothing trigger-specific in the write path.
- **Out of scope here**: *pushing* the approval request to the user (Slack DM on
  a trigger run interrupting). That is the open "HITL/notifications" item on the
  triggers feature — this inbox is the pull view it links to.

---

# Implementation status (2026-09-01)

Steps 1–6 are implemented (goals 1 and 2); step 7 (the inbox) is deliberately
not — but every seam it needs now exists.

| Piece | Where |
| --- | --- |
| `app/agents/hitl.py` — `PendingInterrupt(id, value)`, `pending_approval_requests`, `is_addressed_resume`, `build_resume_command` (moved out of `threads/serialization.py`; worker/router/consumer imports updated) | step 1 |
| `StaleApprovalError` → 409, body `{"error": "stale_interrupt"}` (the other 409 on run-create, distinguishable from `model_unavailable`) | `app/exceptions.py` |
| `GET /threads/{id}` returns `interrupt_id` beside `interrupt_value` | step 2 |
| `RunService._canonical_command` — addressed resume validated against the checkpoint (409 when stale), decisions re-ordered server-side, stored canonical (`{"resume": {<id>: {"decisions": [...]}}}`); legacy and replayed commands pass through with **zero** checkpoint reads | step 3 |
| Slack: cards tagged `hitl:<interrupt_id>:<tool_call_id>` (`block_id`), decisions read back from block ids (emoji demoted to presentation), batch identified by interrupt id instead of the contiguity heuristic, stale clicks marked "Already handled elsewhere" without resuming, checkpoint arbitrates on every click; legacy emoji scan kept as fallback until pre-deploy cards drain | step 4 |
| Web: `interruptId` from live SSE (`interrupt.id`) or rehydrate (`interruptId`); addressed submit `{interrupt_id, decisions: [{tool_call_id, type}]}` with positional fallback; 409 `stale_interrupt` → named error → page reloads to the checkpoint's real state | step 5 |
| Tests: 24 new (hitl unit + a real-graph round trip proving the extracted id IS langgraph's resume-map key, RunService canonicalization on the SQLite lane, block-id protocol + stale flows, exception mapping). Backend: 981 passed, ruff/mypy clean | step 6 |

Left for step 7 (goal 3): partial index on `threads.last_run_status = 'interrupted'`
+ `GET /approvals`. The endpoint's per-thread detail read is
`hitl.pending_approval_requests`, its staleness handling is the 409 already in
place, and the web resume path it links to is done.
