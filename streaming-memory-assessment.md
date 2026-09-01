# Streaming memory assessment — why the tab hits ~1.5GB

**Date**: 2026-09-01
**Symptom**: when an agent run streams a lot of tokens, the auxilia browser tab grows to ~1.5GB.

## TL;DR

It is not one leak — it is **quadratic allocation churn** across three layers, and the
number matches a known upstream problem: LangChain's own support article on
deepagents + token streaming reports "memory spikes (1–1.5 GB or higher)" with
`streamMode: ['messages', 'updates']`, because **every token materializes a new
`AIMessageChunk` object plus a full re-merge of the accumulated message**. We run
that exact stack in the browser, with `values` snapshots on top, and re-render the
whole chat page at token rate. Retained memory is bounded (roughly the final thread
state ×2–3); the 1.5GB is mostly garbage V8 hasn't collected because the tab never
goes idle while streaming.

Upgrading `ai` / `@ai-sdk/react` will change nothing — the chat page doesn't use the
AI SDK at all (only a type import in `prompt-input.tsx`). The two upgrades that do
matter are **streamdown 1.6 → 2.6** (2.5 stops re-rendering completed blocks) and,
more importantly, **implementation changes** listed below.

## Layer 1 — `@langchain/langgraph-sdk` `useStream`: O(n²) per-token work (biggest)

`web/src/app/(protected)/agents/[id]/chat/[threadId]/page.tsx:500` uses
`useStream` + `FetchStreamTransport` (SDK 1.7.5). Inside the SDK
(`dist/ui/manager.js`, `dist/ui/messages.js`), **every `messages` SSE event —
i.e. every token chunk —** does all of the following:

1. `MessageTupleManager.add`: coerces the chunk to an `AIMessageChunk` and
   `prev.concat(chunk)` — string-concatenates the full accumulated `content`
   (and DeepSeek's `additional_kwargs.reasoning_content`) into brand-new strings.
   Cost per token is O(message length) → **O(n²) bytes allocated over one response**.
2. `toMessage(chunk)` → `chunk.toDict()`: re-serializes the entire accumulated
   message to a fresh plain object.
3. `setStreamValues`: `messages.slice()` (copies the whole message array) + a new
   values object.
4. `setState` → `notifyListeners()` — **unthrottled**, see Layer 3.

On the measured thread (~110KB of AI text + reasoning ≈ 7,000+ token events), step 1
alone churns ~30MB, steps 2–3 add tens more, and — dominating everything — each of
those 7,000+ events triggers a full `ChatPage` re-render (Layer 3): 251 messages'
worth of React elements rebuilt per event easily exceeds **1MB per render × thousands
of renders = multiple GB of element churn** over a long run. Subagent tokens stream
too (`subgraphs=True`), multiplying this during parallel subagent runs.

Upstream confirmation: [LangChain support — "How do I resolve memory issues when
streaming tokens with deepagents and subagents?"](https://support.langchain.com/articles/8854872772-how-do-i-resolve-memory-issues-when-streaming-tokens-with-deepagents-and-subagents)
— it names the same symptom ("significant memory spikes (1–1.5 GB or higher)") and the
same cause ("Messages mode yields one `AIMessageChunk` per LLM token across all graph
levels, including subagents … a single run can produce 10,000+ chunk objects"). (Their
server-side advice — callbacks instead of chunk objects, or `subgraphs: false` —
targets backend stream iteration; in our architecture the equivalent lever is the
backend adapter and what the browser is made to parse. The React SDK has no fix as
of 1.10.0, whose changelog contains no perf work.)

## Layer 2 — backend streams 3 redundant modes, one of them O(n²) on the wire

`backend/app/agents/runtime.py:616`:

```python
stream_mode=["messages", "values", "updates"], subgraphs=True
```

- **`values` emits the entire graph state after every superstep** — all messages
  plus the deepagents `files` dict. Measured on the thread that hit 1.5GB
  (`output-f0c70a93823fdf23.json` at repo root — 251 messages: 120 AI + 127 tool,
  ~600KB final state, `files` empty, weight dominated by tool outputs ~189KB and
  reasoning ~90KB): emitting a snapshot as each message lands sums to **~83MB of
  JSON** parsed browser-side over one thread — and `JSON.parse` output typically
  occupies 2–4× the JSON size as JS objects, so ~200–300MB of allocation from
  `values` alone.
- **`updates`** duplicates every node's output messages a third time.
- **Reattach replays from `last_event_id=0`** (`use-durable-run.ts:75`), so
  reconnecting to a long run re-parses the *entire* O(n²) event log in one burst —
  the worst-case memory moment.

The client genuinely needs: token deltas (`messages`), `__interrupt__` + `todos` +
final state (`values`), and subagent lifecycle (`updates` namespaces). It does not
need `files` in every intermediate snapshot, nor full message arrays in every
`values` event — but the SDK replaces `values` wholesale, so trimming requires care
(see recommendations).

## Layer 3 — the chat page re-renders at token rate

`useStream` is called **without the `throttle` option** (page.tsx:500), so the SDK's
`useSyncExternalStore` subscription fires on *every* internal `setState` — at least
once per SSE event, often more (subagent `bumpVersion`). The existing
`useThrottledValue(…, 60)` (page.tsx:549, 612) only throttles *which data the
children see*; **the 1,500-line `ChatPage` component itself still re-renders per
token**, rebuilding the React element tree for the entire conversation each time.

Additional per-render cost: `(thread as any).toolCalls` (page.tsx:610) is a getter
that runs `getToolCallsWithResults()` over **all** messages — full scan + array/map
allocation, per token.

What's already good: `MessageResponse` is `memo`-ized with a `children` string
comparator (message.tsx:121), so completed messages don't re-parse markdown;
`ReasoningContent` is memoized; throttling caps Streamdown re-parses of the live
message at ~16Hz.

## Layer 4 — streamdown 1.6.11 (minor)

The live message is re-parsed and every one of its blocks re-rendered at 16Hz while
it streams. Streamdown 2.x is a rewrite:
[2.5 — "Completed blocks no longer re-render when new streaming content arrives"](https://vercel.com/changelog/streamdown-2-5),
[2.3 — code blocks render plain text before shiki loads](https://vercel.com/changelog/streamdown-2-3),
[v2 — smaller bundle, plugin architecture](https://vercel.com/changelog/streamdown-v2).
It's a major (plugin-based API) — check `Streamdown` props usage in `message.tsx` /
`reasoning.tsx` during migration.

## Library version audit

| Package | Installed | Latest | Verdict |
| --- | --- | --- | --- |
| `@langchain/langgraph-sdk` | 1.7.5 | 1.10.0 | No perf/memory fixes in between; the per-token churn is unfixed upstream. Upgrade is safe but won't move the needle. (1.9.31 has an unrelated HITL-interrupt-after-reload fix we may want.) |
| `streamdown` | 1.6.11 | 2.6.0 | **Worth upgrading** — 2.5 stops re-rendering completed blocks. Major-version migration. |
| `@langchain/core` | 1.1.34 | 1.2.9 | No chunk-concat optimization found; upgrade neutral. |
| `ai` / `@ai-sdk/react` | 6.0.67 / 3.0.63 | 7.x / 4.x | **Not on the streaming path** (type-only import). Irrelevant to this issue. |

## Upstream landscape (langgraphjs issue sweep, 2026-09-01)

Searched `langchain-ai/langgraphjs` issues/PRs for memory, re-render, throttle, and
useStream performance. **No open issue covers our exact browser-side symptom on the
legacy path, and no fix is coming to it** — but upstream has already solved the
mechanism in a *new* React stack we don't use yet:

- **The legacy path (ours)**: `@langchain/langgraph-sdk/react` `useStream` +
  `FetchStreamTransport` (`dist/react/stream.custom.js`). Per-event
  `notifyListeners` and per-token chunk merging are inherent to its `StreamManager`;
  changelog through 1.10.0 has zero perf work. This is maintenance-mode code.
- **The new stack**: [`@langchain/react`](https://github.com/langchain-ai/langgraphjs/tree/main/libs/sdk-react)
  (v1.0.33, actively developed, used by LangChain's own open-swe UI). Full rewrite:
  `StreamController` + `ChannelRegistry` + per-channel *projections* with selector
  hooks (`useMessages`, `useToolCalls`, `useValues`) — only components subscribed to
  a projection re-render, and store writes are **coalesced per macrotask**.
  [PR #2387](https://github.com/langchain-ai/langgraphjs/pull/2387) fixed exactly our
  failure mechanism there ("per-event `store.setState` calls fire
  `useSyncExternalStore` notifications per event"; its regression test asserts a
  200-delta burst produces <10 notifications). First-class subagent support
  (`SubagentMap`, discovery snapshots) replaces `filterSubagentMessages`.
- **The new wire format**: the new stack speaks the
  [Agent Streaming Protocol](https://github.com/langchain-ai/agent-protocol)
  (`@langchain/protocol`) — thread-centric, **delta-based** (`message-start`,
  `text-delta`, `reasoning-delta`, `message-finish`, tool lifecycle events) with
  seq-numbered replay. That eliminates both the `values` snapshot firehose *and*
  per-token chunk-object merging at the protocol level. There are
  [Python bindings + FastAPI server stubs](https://github.com/langchain-ai/agent-protocol)
  (`py-langchain-protocol`), and our durable-run Redis event log with
  `last_event_id` replay is architecturally aligned with the protocol's replay
  contract — the migration is an event-format change, not an architecture change.
  Frontend-side, `HttpAgentServerAdapter` targets exactly our shape (self-hosted
  HTTP/SSE backend, custom paths, cookie/header auth via `fetch` override).
- **Maturity caveats**: the custom-adapter path is young — open issue
  [#2754](https://github.com/langchain-ai/langgraphjs/issues/2754) (2026-08-27,
  self-hosted custom-transport `getHistory` goes out unauthenticated) and
  [#2705](https://github.com/langchain-ai/langgraphjs/issues/2705) (the same
  notification-storm class of bug in `useChannel` replay, closed 2026-08) show the
  edges are still being sanded.

**Conclusion**: the short-term app-side fixes below stand on their own — nothing
upstream will rescue the legacy path. Medium-term, the durable answer is migrating
to `@langchain/react` + Agent Streaming Protocol (backend emits protocol-v2 deltas
from the run event log; frontend uses `HttpAgentServerAdapter` + selector hooks),
which fixes all three layers by design. Worth a separate migration assessment once
the custom-adapter issues settle.

### Migration shape (assessed 2026-09-01)

**No hand-written adapter is needed.** The stock `HttpAgentServerAdapter` is built
for exactly our deployment ("point `useStream` at a single HTTP endpoint that
speaks the v2 protocol"): it takes `paths` overrides (default
`/threads/:threadId/{commands,stream,state}` — maps directly onto our
`/api/backend` proxy routes), a `fetch` override (where our 409
`model_unavailable` / `stale_interrupt` handling from `use-durable-run.ts` moves),
and cookie auth rides along since the proxy is same-origin. A custom
`AgentServerAdapter` would only be worth writing as a *client-side translator* of
our legacy SSE — zero backend change, but it keeps the O(n²) `values` wire cost, so
it's the worse half of the win. Since we own the backend, emit the protocol there.

**What the backend takes.** The [Agent Streaming Protocol](https://github.com/langchain-ai/agent-protocol)
maps ~1:1 onto machinery we already have:

| Protocol requirement | What we already have |
| --- | --- |
| `POST /threads/{id}/stream` (filtered SSE) + `POST /threads/{id}/commands` + `GET /threads/{id}/state` | runs stream endpoint, cancel endpoint, thread GET |
| `run.start` / cancel commands | `RunService.create` / cancel |
| Ring-buffer replay, monotonic `seq`, client sends `since` | durable-run Redis event log + `last_event_id` replay |
| HITL: `input.requested` event carries `interruptId`; client resumes with `input.respond` echoing it | checkpoint-keyed interrupt ids + stale-resume 409 (PR #307) — same design |
| Channels: `messages` deltas (`message-start`/`content-block-delta`/…), `tools` lifecycle, `lifecycle`, optional `values`/`updates` | `LangGraphStreamAdapter` — this is the real work: rewrite it to emit protocol deltas instead of values snapshots |

There is **no runtime Python server** for the protocol — only generated
TypedDict/Literal payload typings (`py/` bindings) and FastAPI stubs
auto-generated from the OpenAPI spec — so the astream→protocol translation in
`stream.py` is hand-rolled (bounded: token deltas from `messages` mode, tool
lifecycle from `updates`, subgraph namespaces we already emit).

**What the frontend takes.** Add `@langchain/react@1.0.33` (+ `@langchain/protocol`
typings; it brings its own compatible `@langchain/langgraph-sdk`), bump
`@langchain/core` 1.1.34 → ≥1.1.48. Then rewrite the chat page's stream layer:
`useStream({ transport: new HttpAgentServerAdapter(...) })` + selector hooks
replace `thread.messages`/`toolCalls`/`interrupt`; `useThrottledValue` and most of
`use-durable-run.ts` go away (protocol replay/reconnect is built in); the subagent
components re-type from `@langchain/langgraph-sdk/ui`'s `SubagentStreamInterface`
to the new `SubagentMap`/discovery snapshots; the `toSdkMessages` snake_case
restoration hack likely dies too (the adapter's `getState` bypasses the axios
interceptor). Caveat to re-check at migration time: open issue
[#2754](https://github.com/langchain-ai/langgraphjs/issues/2754) — custom-adapter
`getHistory` ignores `defaultHeaders`/`fetch` (used for subagent history
hydration); likely survivable for us because auth is a same-origin cookie, but
verify.

Rough scope: one backend PR (protocol emitter + 3 endpoint shims, keeping legacy
SSE for Slack/invoke), one frontend PR (chat page + subagent components). The
legacy and new stacks can run side by side behind a route during the cutover.

## Recommendations, in impact order

1. **Stop per-token re-renders of `ChatPage`.** Two options:
   - Try `throttle: true` in the `useStream` options — the SDK coalesces
     notifications with a 0ms trailing timer, collapsing same-tick bursts to one
     render per macrotask. (Avoid `throttle: <ms>` — the SDK's implementation is a
     trailing *debounce*: under a continuous token flow faster than the interval it
     would starve updates entirely until the stream pauses.)
   - Or restructure: extract the conversation body into a `memo`-ized component fed
     only the throttled `messages`/`toolCalls`, so the component that owns
     `useStream` renders almost nothing itself.
2. **Don't read `thread.toolCalls` on every render** — it's a full recompute. Derive
   tool calls from the throttled messages via the existing
   `computeToolCallsFromMessages` (already memoized) and drop the getter read, or
   sample the getter inside the same throttle.
3. **Trim the `values` firehose backend-side.** On the measured thread the cost is
   the `messages` array re-sent in every snapshot (~83MB cumulative), not `files`
   (empty there — still worth stripping for sandbox-heavy threads). The real cut —
   dropping intermediate `messages` from `values` and letting the `messages` chunks
   maintain the list — needs SDK-side care because `setStreamValues` replaces state
   wholesale. Also consider replaying reattaches from a checkpoint instead of
   `last_event_id=0`.
4. **Upgrade streamdown to 2.6** for the completed-block re-render fix.
5. **Verify empirically** (separate port 3100 per convention): stream a long
   response with DevTools → Memory. Take a heap snapshot after the run + manual GC —
   if retained heap drops to tens of MB, this confirms churn (not a leak) and the
   fixes above are the right lever; the allocation-instrumentation timeline will
   show the hot stacks (`concat`/`toDict` and React element creation).

## Sources

- [LangChain support: memory issues streaming tokens with deepagents/subagents](https://support.langchain.com/articles/8854872772-how-do-i-resolve-memory-issues-when-streaming-tokens-with-deepagents-and-subagents)
- [Streamdown 2.5 changelog](https://vercel.com/changelog/streamdown-2-5) · [2.3](https://vercel.com/changelog/streamdown-2-3) · [v2](https://vercel.com/changelog/streamdown-v2) · [1.6](https://vercel.com/changelog/streamdown-1-6-is-now-available-to-run-faster-and-ship-less-code)
- [langgraphjs releases](https://github.com/langchain-ai/langgraphjs/releases)
- SDK internals read from `web/node_modules/@langchain/langgraph-sdk/dist/{react/stream.custom.js, ui/manager.js, ui/messages.js}` (v1.7.5)

## Measured A/B results (2026-09-01, Part 1 quick fixes — PR #310)

Method: `web/scripts/measure-stream-memory.mjs` (Playwright + CDP heap sampling
at 250ms) against production builds — `main` (worktree, :3101) vs
`perf/streaming-memory-quick-fixes` (:3100), same backend (:8000, branch code —
`files` was empty on this thread so the values trim is not a factor here). Same
thread (agent with 0 MCP servers, deepseek-v4-flash), same prompt, run order
M-B-B-M so each build ran once early / once late as history grew. All four runs
produced near-identical ~31.9K-char essays; pair 2 was also duration-matched
(~37–38s).

| run     | stream | PEAK heap | post-GC retained | script CPU | style recalcs |
| ------- | ------ | --------- | ---------------- | ---------- | ------------- |
| main    | 75.8s  | 164.1 MB  | 88.7 MB          | 6.8s       | 16,717        |
| branch  | 38.3s  | 50.9 MB   | 22.1 MB          | 3.8s       | 9,224         |
| branch2 | 36.9s  | 50.7 MB   | 22.8 MB          | 3.6s       | 8,834         |
| main2   | 38.4s  | 123.8 MB  | 90.9 MB          | 5.1s       | 9,222         |

- **Peak JS heap: 2.4–3.2× lower** on the branch (124–164 MB → ~51 MB), on a
  *small* thread (single long text response, no subagents, no tool storm). The
  1.5GB thread's costs are quadratic in conversation size, so the absolute gap
  compounds there.
- **Retained heap after GC: ~4× lower** (≈90 MB → ≈22 MB) — main holds ~90 MB
  live after the stream ends (main2's *baseline* was already 84.8 MB right
  after loading history); the branch settles at ~22 MB.
- **Main-thread CPU ~30–45% lower** at matched duration (script 5.1s → 3.6s).
- Time series JSONs: `web/scripts/out/mem-{main,branch,branch2,main2}-*.json`.

Caveat: JS heap of the page, not full Task-Manager footprint; single thread,
prompt mode only (reattach replay not yet measured). Build gotcha found on the
way: `.next-mem/` (the isolated dist dir used for these builds) was not
gitignored, so Tailwind v4's auto content detection scanned its minified build
chunks and generated broken CSS ("Missed semicolon" at a moving column) —
fixed by adding `.next-mem/` to the root `.gitignore`.
