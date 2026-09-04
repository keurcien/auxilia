# Subagent HITL: what `@langchain/react` 1.0.33 changes, and what it implies for auxilia

Assessment written 2026-09-04. No code changed. Companion to issue #301
("Subagent tool approvals are silently dropped at run time").

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
