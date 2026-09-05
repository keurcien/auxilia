# Subagent HITL: what `@langchain/react` 1.0.33 changes, and what it implies for auxilia

Assessment written 2026-09-04, verified by spike 2026-09-05 (see the update below). No code changed. Companion to issue #301
("Subagent tool approvals are silently dropped at run time").

## Status 2026-09-05 — implemented (uncommitted, in the working tree)

Everything in "Revised work, with sizes" below is done (the optional SDK bump is not needed):

- Backend: `ResolvedAgent.compile` gates subagents; `hitl.load_interrupt_scope` follows the
  root pending write into `tools:<task-id>` (nested levels too, bounded by
  `MAX_SUBAGENT_DEPTH`; a root approval costs one extra keyed probe) and exposes the paused
  `task` call; `pending_approval_requests` / `build_resume_command` take that scope;
  `RunService._canonical_command`, `ProtocolService.thread_state` (interrupt `namespace`),
  the Slack consumer (card names the subagent) and handlers use it. `ProtocolEmitter`
  emits `input.requested` under the paused agent's namespace and swallows the `task`
  `tool-error` that is the interrupt bubbling up.
- Web: `page.tsx` splits `stream.interrupts` into the root one and the subagents' (keyed
  by content so the memoized body is not re-rendered per token); `SubAgentCard` claims its
  interrupt (`findSubagentInterrupt`: namespace first, action-request fallback after a
  reload), renders nested `ToolStep`s as awaiting approval with the approve/deny footer,
  shows the needs-approval badge instead of the spinner, and resumes through its own
  `useHitlApprovals`; the chain stays open while a card is paused.
- Tests: `tests/agents/test_hitl.py` (scope resolution, real gated subagent end to end),
  `tests/agents/protocol/test_emit.py` (`subagent_scenario`: namespaced request, no task
  tool-error, resume), `test_service.py` (state namespace), Slack consumer;
  `message-helpers.test.ts` for the split/claim helpers. Backend suite 1035 passed, web
  vitest/tsc/eslint clean.
- First live test (2026-09-05, Slides subagent): the interrupt fired and the first approval
  resumed correctly, but the card froze afterwards and the second approval failed with a 400
  ("Decisions do not match the pending approvals"). Cause: the SDK pauses every subscription
  on a run's terminal lifecycle and the scoped projections behind `useMessages` /
  `useToolCalls` / `useValues` never resume (`resumeOnPause` is off for them, upstream `main`
  included), so the resumed run's subagent events (tool result, retried call, new interrupt's
  target) never reached the card; the stale call matched the new interrupt by name and the
  recorded decision auto-resubmitted. Fix: `web/src/hooks/use-subagent-projections.ts` — the
  SDK's own projection specs, subscribing through a thread whose handles resume across runs;
  the card uses those. Unit-tested; the live flow still needs a second try.
- Review round (Codacy + cubic): addressed resumes pick their interrupt by id and
  `thread_state` reports every pending interrupt, so two subagents pausing together each
  resume in turn (a card holds its completed batch while a run is in flight); a hydrated
  interrupt is addressed with the SDK's discovery key `tools:<tool_call_id>` and the card
  accepts either key, so no matching by content remains; the emitter swallows a
  `tool-error` only for the `task` tool, with the repr shape and an exactly announced id;
  the Slack context line is mrkdwn-escaped; the resuming iterator is an explicit
  async-iterator object with a finished flag.

## Update 2026-09-05 — verified by running it

Re-checked after the user reported that "latest langchain/langgraph detect subagent HITL".
Upstream since the 09-04 assessment: langchain 1.4.0 (09-03) is the `langchain.mcp`
adapter, nothing about subagents; deepagents 0.7.12/0.7.13 add subagent forking modes;
langgraph Python is still 1.2.11 (08-11). The only relevant release is
`@langchain/langgraph-sdk` 1.10.2 / `@langchain/react` 1.0.35 (09-04, langgraphjs#2780):
`stream.interrupts` stays truthful after sequential `respond()` calls on parallel
interrupts. Corroborating evidence that upstream treats nested subagent HITL as a working
feature: deepagents-code #4771 "keep `task` timers monotonic across nested subagent HITL"
and langchain-quickjs #4401 "propagate JS `task()` subagent interrupts" (July 2026).

So nothing new is required from upstream: **the detection already works on the versions
we have installed** (langgraph 1.2.11, deepagents 0.5.6, langchain 1.3.17, sdk 1.10.0).
Two scratch spikes proved the 09-04 table instead of reasoning from source. Both used
`build_runnable` + `build_agent_middleware` (our real stack), a scripted model, an
`InMemorySaver`, and the real `hitl.py` helpers; the only change from production was
passing `interrupt_on={"dangerous": True}` to the subagent's middleware.

### Spike 1 — `astream(subgraphs=True)`, checkpoint, resume

| Claim | Result |
| --- | --- |
| Subagent's gated tool interrupts | yes — `__interrupt__` on the `tools:<task-id>` values envelope |
| Interrupt reaches the root checkpoint | yes — root `pending_writes` = `(<parent tools task id>, "__interrupt__", (Interrupt,))` |
| Id is 32-hex, same in both namespaces | yes — e.g. `67678b50…7ab429` on root and on `tools:<task-id>` |
| `hitl.pending_interrupt(root)` | works unchanged |
| `hitl.pending_approval_requests(root)` | **wrong id**: `approval-0` (root's last AI call is `task`) |
| `hitl.pending_approval_requests(<tools:<task-id>> tuple)` | **right id**: `sub-call-0` — the existing matcher is correct, it is just fed the wrong checkpoint |
| Namespace derivation | `tools:<task_id of the root pending write>` — identical to `protocol/service._task_namespace` |
| `build_resume_command` + `Command(resume={id: {...}})` | resumes; subagent ToolMessage lands under `tools:<task-id>`, parent continues to its final answer |
| Two sequential gated calls in one subagent (deepagents #1762 caveat) | both interrupt with distinct ids and both resume cleanly |

### Spike 2 — `astream_events(version="v3")` through `ProtocolEmitter` (the real wire)

Envelope order at the pause: `values` on `["tools:<task-id>"]` carrying `interrupts=[…]`,
then root `tools` **`tool-error` for the `task` call** with `message="(Interrupt(…),)"`,
then root `values` carrying the same interrupt, then `lifecycle interrupted` for the
subagent namespace. The emitter today produces:

- `input.requested` once, with `namespace: []` — because `_on_values` returns early in the
  namespaced branch before looking at `interrupts`, so the root copy is the one emitted.
  Detection works; card scoping does not.
- **`tools.tool-error` for `task-call-1`** — new finding, not in the 09-04 table. langgraph
  reports the `GraphInterrupt` that bubbles through the `task` tool as a tool failure. The
  SDK's `SubagentManager.complete(id, message, "error")` then marks the card *errored*
  with the `Interrupt(...)` repr as its error text for the whole pause. On resume the
  subagent streams again and `markRunning` flips it back, so it self-heals, but the paused
  state is displayed as a failure. The emitter must swallow that one event (the message
  starts with `(Interrupt(`; or hold `tool-error` until the next root `values` and drop
  it when that envelope carries an interrupt).
- On resume: root `tool-started` for the same `task-call-1` again, subagent `lifecycle
  started` again, then the subagent's `dangerous` `tool-finished`, then `task`
  `tool-finished` and `lifecycle completed`. Nothing to fix there.

`aget_state` after the pause: `next=("tools",)`, `tasks=[("tools", [<id>])]` — the same
shape a root HITL pause has, so `thread_state` needs only the namespace added.

### Revised work, with sizes — the plan as executed (see Status above; names below are the final ones)

Backend (≈1.5–2 days)

1. `ResolvedAgent.compile` passes `interrupt_on=self.prepared.interrupt_on`; rewrite the
   three stale "no checkpointer" docstrings (`build_agent_middleware`, `compile`,
   `SUBAGENT_RECURSION_LIMIT`). ~0.5 h.
2. Namespace-aware approvals. `pending_interrupt` also returns the pending write's
   `task_id`; `hitl.load_interrupt_scope(checkpointer, thread_id, interrupt_id=…)` loads
   the root tuple, follows `tools:<task_id>` when the interrupting namespace is a subagent
   (depth-capped), and `pending_approval_requests(root, scope)` runs the *existing* matcher
   on that tuple. Same for the checkpoint `build_resume_command` validates against.
   Parallel subagents pausing together: `pending_interrupts` lists them all,
   `load_interrupt_scopes` locates each, an addressed resume picks its own by id. Call sites: `threads/router.py`,
   `protocol/service.thread_state`, `slack/consumer.py`, `slack/handlers.py`,
   `RunService._canonical_command`; `runs/worker.py` only uses `pending_interrupt` and
   is untouched. ~0.5 day incl. tests.
3. Emitter: (a) handle `interrupts` in the namespaced `_on_values` branch and emit
   `input.requested` with the real namespace (the id dedupe already drops the root copy);
   (b) suppress the `task` `tool-error` caused by the interrupt and keep it out of
   `_tool_finished_ids`. `tests/agents/protocol/test_emit.py` already drives a real
   `create_agent` + `task` subagent with a scripted model, so the new case is one more
   scenario. ~3 h.
4. `thread_state`: put `namespace: ["tools:<task-id>"]` on the interrupt entry so a
   reload lands the approval on the right card (SDK `Interrupt.namespace` exists). ~1 h.
5. Slack: prefix the card title with the subagent name. ~1 h.

Frontend (≈1.5 days)

1. `SubAgentCard` picks `stream.interrupts.filter(i => sameNamespace(i.namespace,
   subagent.namespace))`; fallback (until backend 3a ships): an interrupt with
   `namespace: []` whose `action_requests` match none of the root tool calls but match the
   card's. ~2 h.
2. Nested `ToolStep` gets `state=getToolStepState(tc, cardInterrupted, cardHitlNames)`
   and the `approval` prop; card `meta` shows the needs-approval badge instead of the
   spinner; `ChainOfThought.lockOpen` includes nested pending approvals. ~3 h.
3. One `useHitlApprovals` per card (the hook is already generic) calling
   `stream.respond(response, { interruptId })`; the SDK resolves the namespace. ~2 h.
4. Local "paused" status derived from the scoped interrupt (the SDK snapshot has no such
   status). ~1 h.
5. Reload path, depends on backend 4 and on how the SDK's hydrate copies
   `tasks[].interrupts[].namespace` — verify before relying on it. ~2–3 h.

Optional: bump `@langchain/langgraph-sdk` to 1.10.2 / `@langchain/react` to 1.0.35 for
langgraphjs#2780 (parallel subagents each pausing) and #2788. Not a prerequisite.

Total ≈ 3.5–4 developer-days for a complete feature (web + Slack + reload), about one
day for the minimum that makes approvals stop being silently dropped (backend 1–3a +
frontend 1–3). The editor toggle stays; drop the "hide the setting" suggestion from #301.

Spike scripts (scratch, not committed): `subagent_hitl_spike.py`,
`subagent_hitl_v3_spike.py` in the session scratchpad; the logic is small enough to
re-create from the tables above.

## TL;DR

- The "1.0.33" is `@langchain/react`. Its own release note is a dependency bump; the
  behaviour lives in `@langchain/langgraph-sdk`, which PR #312 moved from 1.7.5 to 1.10.0.
  The relevant change is **sdk 1.9.29, PR langgraphjs#2672** *"surface nested interrupts on
  stream.interrupts"*: `input.requested` events from any namespace (subagents included) are now
  mirrored onto `stream.interrupts` live, each carrying its `namespace`, and
  `respond({ interruptId })` resolves that namespace automatically (#2676).
- Nothing changed server-side. Subagent HITL has been **checkpointed and resumable in LangGraph
  since deepagents 0.5.x** (deepagents#602, Dec 2025): the `task` tool spreads the parent's
  `configurable` into the subagent, which forwards `__pregel_checkpointer` and
  `__pregel_checkpoint_ns`, so the subagent runs as a nested subgraph under `tools:<task-id>`.
  That is exactly the namespace our history endpoint already reads.
- **Our runtime's premise is stale.** `build_agent_middleware` / `ResolvedAgent.compile` say a
  subagent "runs without a checkpointer, which is what drops the approval gate" and therefore pass
  `interrupt_on=None`. The checkpointer is there. The gate is missing only because we don't add
  `HumanInTheLoopMiddleware` to the subagent stack.
- Closing #301 is therefore mostly plumbing, not architecture: add the middleware to subagents,
  teach `hitl.py` to find the gated tool call in the interrupting namespace instead of the root
  `messages` channel, and give the subagent card an approve/deny path in the web app.

## 1. Upstream facts, verified against installed code

### 1.1 Client (`web/node_modules`)

| Package | Installed | Note |
| --- | --- | --- |
| `@langchain/react` | 1.0.33 | every 1.0.3x entry is "Updated dependencies" |
| `@langchain/langgraph-sdk` | 1.10.0 | was 1.7.5 before PR #312 |
| `@langchain/core` | 1.2.9 | |

Behaviour in `@langchain/langgraph-sdk/dist/stream/controller.js`:

- `#recordInterrupt` (≈1728): every `input.requested`, whatever `params.namespace`, is appended to
  `rootStore.interrupts` with `namespace` on the entry. So `stream.interrupt` /
  `stream.interrupts` now include subagent interrupts while the run is live. Before 1.9.29 a
  root-only filter dropped them live but hydrate seeded them from `state.tasks`, so they appeared
  only after a reload.
- `respond()` (≈1015): resolves the namespace for the given `interruptId` and sends
  `{ namespace, interrupt_id, response, update?, goto?, config, metadata }` as `input.respond`.
- `respondAll()` exists for several interrupts at one checkpoint (parallel subagents each pausing).
- `SubagentDiscoverySnapshot.status` is still `"running" | "complete" | "error"`. There is no
  "interrupted" status; a paused subagent looks like a running one.

### 1.2 Server (`backend/.venv`, langchain 1.3.17, langgraph 1.2.11, deepagents 0.5.6)

- `deepagents/middleware/subagents.py:442-460`: `subagent_config = {"configurable":
  {**runtime.config["configurable"], "ls_agent_type": "subagent"}}` then `subagent.ainvoke(...)`.
  The spread carries `__pregel_checkpointer`, `__pregel_checkpoint_ns`, `thread_id`, and the
  resume map. `create_agent` for the subagent is called with no `checkpointer` (591-598) and
  never `checkpointer=False`, so `Pregel._defaults` inherits the parent's.
- `deepagents/middleware/subagents.py:583-585`: a subagent spec's own `interrupt_on` becomes a
  `HumanInTheLoopMiddleware` on the subagent. deepagents itself expects subagent HITL to work.
- `langgraph/types.py:966-971`: `interrupt()` raises `GraphInterrupt(Interrupt.from_ns(value,
  ns=checkpoint_ns))`; the id is `xxh3_128(ns)` (617-618), so a subagent interrupt id encodes
  the subagent's task namespace.
- Propagation to the parent: `langgraph/prebuilt/tool_node.py:982` re-raises `GraphBubbleUp`
  from a tool; `langchain/agents/middleware/tool_error.py:145`, `tool_retry.py`, `model_retry.py`,
  `model_fallback.py` all re-raise it. Our `ToolErrorMiddleware` subclasses the upstream one and
  only supplies the formatter, so it inherits the re-raise. `langgraph/pregel/_runner.py:585-588`
  then writes `(task_id, "__interrupt__", child_interrupts)` into the **root** checkpoint's pending
  writes. The root `values` stream event carries the same interrupts (`pregel/main.py:4221-4228`).
- Resume: `Command(resume={<interrupt_id>: payload})` is placed in `CONFIG_KEY_RESUME_MAP`
  (`_loop.py:914`), which is part of `configurable` and so flows into the subagent through the
  same spread. `_algo.py:622-633` hands each task a scratchpad keyed by the hash of its namespace,
  which is the interrupt id. The parent re-runs only the interrupted `task` tool call because
  `create_agent` dispatches one `Send("tools", [tool_call])` per call (`factory.py:1968`); sibling
  tool results already in the checkpoint are not re-executed. The subagent reloads its own
  checkpoint under `tools:<task-id>` and `interrupt()` returns the decision.
- Payload / resume shapes are unchanged since 1.0: `{"action_requests": [{name, args,
  description}], "review_configs": [...]}` in, `{"decisions": [approve | reject | edit |
  respond]}` out, positional by request. `build_resume_command` already emits the id-keyed form
  whenever the checkpoint yields a 32-hex id.
- Newer Python releases change nothing here. deepagents 0.6.0 narrowed the forwarded config to
  `callbacks/tags/configurable` "so Pregel recognises the subagent as a nested subgraph";
  0.6.8 removed the forwarding in favour of langgraph's ambient-config merge (langgraph#7926).
  Net effect on checkpointing and interrupt propagation: none. Known upstream limitation
  (deepagents discussion #1762): a second interrupt raised by the *same* subagent after a
  state update on resume can be swallowed; sequential gated calls in the ordinary loop are fine
  but should be covered by a test.

## 2. What happens in auxilia today if a subagent tool is gated

1. `Toolset.prepare` computes `interrupt_on` for the subagent's own toolset (the editor lets you
   set "requires approval" on a subagent's tools).
2. `ResolvedAgent.compile` calls `build_agent_middleware(created_at,
   recursion_limit=SUBAGENT_RECURSION_LIMIT)` with no `interrupt_on`, so neither
   `HumanInTheLoopMiddleware` nor `PatchToolCallsMiddleware` is added. The tool runs unasked.
   This is #301, and the fix is one argument.

If you *did* add the middleware today, here is how far the rest of the stack would carry it:

| Stage | Works? | Why |
| --- | --- | --- |
| Interrupt reaches the root checkpoint | yes | propagated by `_runner.py`, id = hash of subagent ns |
| `pending_interrupt()` (worker, state, Slack, threads router) | yes | reads root `pending_writes`, tolerates the tuple form |
| `emit._on_values` → `input.requested` | partly | root envelope emits it with `namespace: []`; the subagent's own envelope is dropped by the early `return` in the namespaced branch, so the client never learns which subagent paused |
| `pending_approval_requests()` | **no** | matches `action_requests` against the **root** `messages` channel's last AI message, whose only call is `task`; falls back to `approval-<i>` ids |
| `build_resume_command()` | degraded | id-keyed resume is correct, but `expected` comes from the broken matcher, so clients must send `approval-<i>` ids positionally |
| `input.respond` → `RunService.create(command={"resume": ...})` | yes | ignores `namespace`; LangGraph routes by id |
| Resume execution | yes | parent re-runs only the `task` Send; subagent resumes from its checkpoint |
| Web: `stream.interrupt` set | yes (new) | sdk ≥1.9.29 mirrors nested interrupts to root |
| Web: something to click | **no** | `getToolStepState` only marks **root** tool calls whose name is in `action_requests`; the nested `ToolStep` inside `SubAgentCard` never receives `approval` and keeps spinning |
| Web: `useHitlApprovals` fires | **no** | `pendingToolCalls` is derived from root `toolCalls`; empty for a nested interrupt, so no batch is ever complete |
| Slack cards | degraded | posted from root checkpoint with `approval-<i>` ids; approve path depends on the matcher |
| Reload / hydrate | partly | `thread_state` seeds the root interrupt; the subagent card's history shows the gated call as running |

## 3. Implications and proposed changes (not implemented)

### Backend

1. **Gate subagents.** `ResolvedAgent.compile` passes `interrupt_on=self.prepared.interrupt_on`
   to `build_agent_middleware`. That also turns on `PatchToolCallsMiddleware` for subagents,
   which is correct now that we know they are checkpointed (a cancelled run can leave a dangling
   call in the subagent's namespace too). Rewrite the docstrings in `build_agent_middleware`,
   `ResolvedAgent.compile` and `SUBAGENT_RECURSION_LIMIT` that claim there is no checkpointer.
   The recursion-limit remark stays true: `task` does not forward `recursion_limit`.
2. **Locate the gated call in its namespace.** `hitl.pending_interrupt` should also return the
   pending write's `task_id`. For a propagated interrupt that task is the parent's `tools` Send,
   and the subagent's namespace is `tools:<task_id>`, the same derivation
   `protocol/service._task_namespace` uses for history. `pending_approval_requests` then loads
   that namespace's checkpoint and matches `action_requests` against *its* last AI message
   (root when the write came from the root `agent` task). Real `tool_call_id`s flow to the web
   client, Slack and `build_resume_command` unchanged.
3. **Emit the real namespace.** In `emit._on_values`, handle `interrupts` in the namespaced
   branch too and emit `input.requested` with that namespace (dedup by id already prevents a
   second root copy). The client can then key the approval UI on
   `interrupt.namespace === subagent.namespace`. `input.respond` may keep ignoring `namespace`.
4. **Hydration.** `thread_state` should expose the namespace on the interrupt task entry it
   returns, so a reload lands the approval on the right card. Check what shape the SDK's
   hydrate accepts for nested interrupts before deciding the field.
5. **Slack.** `pending_approval_requests` fix covers the cards; consider prefixing the card
   title with the subagent name, since the tool name alone is ambiguous across agents.
6. **Concurrency.** Two subagents pausing in the same superstep produce two root interrupts.
   `_input_respond` currently rejects batches of more than one response and
   `build_resume_command` assumes one pending interrupt. Either accept several ids in one
   command (the SDK's `respondAll`) or, more simply, resume one at a time and document that the
   second card stays pending until the first resume's run is terminal.
7. **Tests.** Add a runtime test: supervisor with a gated subagent tool → interrupt visible on
   the root checkpoint with a 32-hex id → id-keyed resume → subagent's ToolMessage lands under
   `tools:<task-id>`. Cover two sequential gated calls in one subagent (the #1762 caveat).

### Frontend

1. **Scope interrupts to a card.** Pass `stream.interrupts` (not just `interrupt`) down; a
   `SubAgentCard` owns the interrupts whose `namespace` matches `subagent.namespace`. With
   backend change 3 this is exact; without it, fall back to matching `action_requests`
   name+args against the card's own tool calls.
2. **Nested approval UI.** `getToolStepState` gets the card's interrupt so nested calls named in
   `action_requests` render `awaiting-approval`; `ToolStep` already renders the approve/deny
   footer when given `approval`, so the card just has to supply it and `lockOpen` while pending.
   Show the `NeedsApprovalBadge` in the card's `meta` slot instead of the spinner, and let
   `ChainOfThought.lockOpen` include nested pending approvals.
3. **Decision batching per interrupt.** Today one `useHitlApprovals` instance works off root
   `pendingToolCalls`. Move to one collector per interrupt id (root or nested) with the
   pending calls for that namespace, calling `stream.respond(response, { interruptId })`. The
   SDK resolves the namespace; the backend stale-checks the id.
4. **Status.** `SubagentDiscoverySnapshot` has no paused state, so `SubAgentProgress` and the
   header keep saying "Working" while waiting. Derive a local "needs approval" state from the
   scoped interrupt rather than waiting on the SDK.
5. **Hydration.** Depends on backend 4. Until then, after a reload the card shows the gated call
   as running; approval still works from the root interrupt if the fallback matcher in 1 is in
   place.

### Editor

Issue #301 suggested hiding the approval toggle on subagent tools until it works. With the
above it becomes real, so leave the toggle and drop that suggestion from the issue.

## 4. Order of work

1. Backend 1 + 2 + tests (makes the feature exist and gives clients real ids).
2. Frontend 1–3 (makes it usable from the web).
3. Backend 3 + 4, frontend 4–5 (polish: right card, right status, reload).
4. Backend 6 (parallel subagent approvals) only if a real agent design needs it.
