# Conversation body: "one event log, many views" audit

Assessed 2026-09-03 against `@langchain/react` 1.0.33 / `@langchain/langgraph-sdk` 1.10.0
(both current on npm) and the LangChain post
[Token streams to agent streams](https://www.langchain.com/blog/token-streams-to-agent-streams#subagents-and-subgraphs).

Question asked: do we use the "one event log, many views" model, and how much of the chat
render path can be replaced by what the framework already offers?

## Status (2026-09-03, branch `refactor/conversation-body-views`, uncommitted)

Phases A–D below are implemented; E is not (the user's call).

| | Before | After |
| --- | ---: | ---: |
| Web chat-render lines in scope | ≈ 2,390 | 1,840 (+ 150 lines of new unit tests) |
| Diff (backend + web, lockfile excluded) | | 26 files, +842 / −1,713 |
| Bespoke chat endpoints | `GET /threads/{id}/subagents/{tool_call_id}/state` | none — `POST /threads/{id}/history` is real |
| Home-grown message shape | `LCMessage` | none, `BaseMessage` rendered directly |
| Tool-call pairings | 2 | 1 (`pairToolCalls` + `<ToolStep>`) |
| `ai` / `@ai-sdk/react` + 15 unused deps | listed | removed; `@modelcontextprotocol/*` declared |

Files: `chat/[threadId]/{message-helpers.ts, tool-step.tsx, subagent-card.tsx,
conversation-body.tsx, page.tsx}`, `hooks/use-hitl-approvals.ts`,
`backend/app/agents/protocol/{service,router,schemas}.py`. Deleted:
`lib/utils/lc-messages.ts`, `components/ai-elements/subagent{,.test}.tsx`,
`components/ui/badge.tsx`, the subagent-state route and its helpers.

Verified: backend suite (1,024 passed; the one failure is the pre-existing
`catalog/whitelist.yaml` snapshot), vitest (49 incl. 7 new for the helpers),
tsc, eslint (default + pre-commit config), knip clean for the touched code, and
`web/scripts/verify-conversation-views.mjs` against the dev stack as a client:
a tool thread and a two-subagent thread render with no console errors, opening
a card issues `POST /history` with `checkpoint.checkpoint_ns = tools:<id>`,
gets the subagent checkpoint back and shows the nested TASK section.

Deviations from the plan: `useThrottledValue` kept (rewritten to satisfy the
React Compiler lint, 36 lines) — the store ticks once per token macrotask, so
the 60 ms bound still matters; measuring it away is a separate pass. The
undiscovered-`task`-call card is gone; such a call now renders as a plain
tool step, no special branch. `SubAgentProgress` / `SynthesisIndicator` kept
(phase E). Reasoning moved onto the chain rail (2026-09-03): `reasoning.tsx` (228 lines) and
`@radix-ui/react-use-controllable-state` deleted; `groupChains` now yields `reasoning` and
`tool` steps and `ChainReasoningStep` (30 lines) renders them — open while streaming via
`lockOpen`, folded behind the first line once done. The "Reasoned for N seconds" label and
the 2 s auto-close are gone by design. HITL exercised live on 2026-09-03: approving a pending `Slides_read_presentation`
call sent `input.respond` keyed by interrupt id + tool-call id, the run
resumed and completed, the final answer rendered. Not exercised live: a
thread with attachments. Regression caught and fixed the same day: the
React-Compiler-compliant `useThrottledValue` rewrite left a cleared timer
handle set, so under StrictMode (dev) the hook never emitted again and the
conversation rendered empty — cleanup now resets the handle, with a
StrictMode unit test. Note: `/history`, like `/state`, is owner-only
(`authorize_thread`); the deleted route also admitted admin viewers, but their
hydration already failed on `/state` before this change.

## Short answer

Half-way. The root hook and the subagent cards already are framework views over one log
(`useStream` → `messages` / `values` / `subagents` / `interrupt`; `SubAgentCard` opens
`useMessages(stream, subagent)` + `useValues(stream, subagent)`). Around that core sit
~900 lines of glue that either re-implement a projection the SDK ships, adapt framework
objects into a home-grown shape, or work around one backend endpoint we deliberately left
empty. Removing those is possible with the design kept as-is; a couple of optional design
trims would take more.

## What is in scope (web, thread page)

| File | Lines | Role |
| --- | ---: | --- |
| `chat/[threadId]/page.tsx` | 499 | owns `useStream`; converts + throttles messages; derives tool calls; HITL wiring; handlers; init |
| `chat/[threadId]/conversation-body.tsx` | 696 | render tree: turn grouping, tool steps, task-call fallback card, approval footer, MCP widget, loaders, error |
| `chat/[threadId]/message-helpers.ts` | 350 | text/reasoning/attachment extraction, tool-name parsing, tool-call pairing + `tools`-channel overlay, render state, HITL names, MCP artifact getters |
| `lib/utils/lc-messages.ts` | 67 | `LCMessage` plain-object shape + `baseMessageToLC` (WeakMap cache) |
| `components/ai-elements/subagent.tsx` | 420 | `SubAgentCard`, `SubAgentConversation`, `SubAgentProgress`, `SynthesisIndicator` |
| `components/ai-elements/subagent.test.tsx` | 73 | tests only the history-fallback behaviour |
| `hooks/use-protocol-fetch.ts` | 113 | fetch wrapper: same-origin guard, `run.start` bookkeeping, 409 translation |
| `hooks/use-hitl-approvals.ts` | 69 | collect N decisions → one `respond` |
| `hooks/use-throttled-value.ts` | 39 | 60 ms throttle, used twice |
| `lib/utils/tool-content.ts` (+48 test) | 35 | ToolMessage content → text |
| `chat/components/loader.tsx` | 27 | `ThinkingLoader` (+ unused `DotsLoader`) |
| **Total** | **≈ 2,390** | |

Backend counterparts: `threads/router.py::get_subagent_state` (+ 2 helpers, ~75 lines) and
the `POST /threads/{id}/history` stub in `agents/protocol/router.py` (returns `[]` on purpose).

## Where we follow the model, and where we don't

### 1. Root tool calls are rebuilt from messages, not read from `useToolCalls`

`page.tsx:180-186` does `enrichToolCalls(computeToolCallsFromMessages(messages), stream.toolCalls)`:
structure from the message log, live status / error / MCP artifact overlaid from the `tools`
channel. This is *not* gratuitous. Verified in
`langgraph-sdk/dist/stream/controller.js`: on hydrate the SDK seeds **scoped** namespaces
with `seedToolCallsFromMessages` (lines 828, 864) but only `reconcileToolCallsFromMessages`
at the root (line 1712), which backfills entries that already exist. After a page refresh
`stream.toolCalls` is therefore empty at the root, and a message-derived pairing is the only
durable view. Worth an upstream issue; until then the pairing stays.

What *is* removable: the overlay only matters live, because the SDK's assembler builds the
live tool-role message as `new ToolMessage({id, content, tool_call_id})`
(`assembled-to-message.js`) — no `status`, no `artifact` — while hydrated messages carry
both (`serialize_message` → `ToolMessage` coercion). So `enrichToolCalls` is a 60-line
patch over one SDK limitation; it should be documented as exactly that and shrunk to
"status + artifact", nothing else.

### 2. The subagent conversation re-implements the same pairing by hand

`subagent.tsx::SubAgentConversation` (lines 78-215) has its own `getTextFromMessage`,
`parseToolName`, `getToolOutputContent`, tool-result map and MCP-server-prefix matching —
copies of `message-helpers.ts` with extra `toolCallId ?? tool_call_id` / `toolCalls ??
tool_calls` fallbacks. It ignores `useToolCalls(stream, subagent)`, which the SDK does seed
from history and from the scoped `tools` channel.

### 3. Subagent history: a bespoke endpoint stands in for `getHistory`

The SDK hydrates an idle thread's subagent cards itself: on the first scoped
`useMessages(stream, subagent)` mount it calls
`client.threads.getHistory(threadId, { limit: 1, checkpoint: { checkpoint_ns } })`
(`controller.js::#getScopedHistorySeed`, ~line 815) and seeds both the `messages` and the
`toolCalls` stores from `history[0].values.messages`. It only does this when the thread is
idle (`#rootPumpDeferred`, i.e. our `/state` answered `next: []` and no interrupt); active
and interrupted threads keep using the scoped `/stream/events` replay we already serve.

Our `POST /threads/{id}/history` returns `[]`, so the SDK gets nothing and the web app
carries its own path instead:

- `conversation-body.tsx:117-144` — `subagentMessages` state, `fetchedSubagentHistory`
  ref, `loadSubagentHistory` → `GET /threads/{id}/subagents/{tool_call_id}/state`
- `subagent.tsx` — `onOpen`, `fallbackMessages`, `requestedInitialHistory`, the
  "error card starts open → fetch" effect, `convoMessages` fallback
- `subagent.test.tsx` — 73 lines testing only that fallback
- the camelCase key fallbacks in `SubAgentConversation` (that endpoint goes through the
  axios camelCase interceptor; SDK messages never do)
- backend `get_subagent_state` + `_task_description` + `_seed_human_content`

The backend already knows how to resolve a `task` tool-call id to its subgraph checkpoint
(description ↔ seed `HumanMessage` match). Serving that from `/history` when the request
carries `checkpoint.checkpoint_ns = "tools:<tool_call_id>"` makes the whole client-side
fallback disappear, and the SDK also seeds `useToolCalls(stream, subagent)` for free.

### 4. `LCMessage` is a shape from the previous era

`baseMessageToLC` turns the SDK's `BaseMessage` instances into plain objects with both
snake_case and camelCase keys (`tool_calls`/`toolCalls`, `tool_call_id`/`toolCallId`,
`additional_kwargs`/`additionalKwargs`). The camelCase halves only ever came from axios
responses (the old history endpoints); every message the chat renders today is a
`BaseMessage` from `useStream`/`useMessages`. `@langchain/core` 1.2 already gives us:

- `message.type` (+ `isAIMessage` / `isHumanMessage` / `isToolMessage` guards) instead of
  the eight `type === "ai" || type === "assistant"` / `"human" || "user"` checks
- `message.text` instead of `getTextContent`
- `message.contentBlocks` (v1-normalised: `text`, `reasoning`, `image`, `file`,
  `tool_call`) instead of `getReasoningContent` / `getFileAttachments` block-type juggling
- `ToolMessage.status` / `.artifact` / `.tool_call_id`, `AIMessage.tool_calls`

Persisted AI messages are already v1 content-block lists (`output_version: "v1"`, see
`agent-streaming-protocol` memory), so `contentBlocks` is a pass-through for them.

### 5. Type-only imports keep two dependencies alive

`message.tsx` (`UIMessage` from `ai`), `attachments.tsx` (`FileUIPart`,
`SourceDocumentUIPart` from `ai`), `prompt-input.tsx` (`UseChatHelpers` from
`@ai-sdk/react`). knip confirms nothing else uses either package.

### 6. knip baseline (run 2026-09-03)

Unused deps: `@radix-ui/react-{checkbox,progress,scroll-area,select,separator,tabs}`,
`@xyflow/react`, `camelcase-keys`, `cmdk`, `embla-carousel-react`, `radix-ui`,
`react-markdown`, `remark-breaks`, `remark-gfm`, `tokenlens`; devDep
`baseline-browser-mapping`. Unused file `components/ui/badge.tsx`. Unused exports incl.
`DotsLoader`, `isRejectedToolCall`, `LCToolCallEntry` (×2), `PASTEL_MAP`,
`OPTIMISTIC_RUN_TTL_MS`. Unlisted deps: `@modelcontextprotocol/sdk`, `@modelcontextprotocol/ext-apps`.

## Plan

Ordered so each step lands on its own and keeps the UI pixel-identical unless flagged.

### A. Real `/history`, delete the subagent-history fallback (backend + web, ≈ −200 lines)

1. `ProtocolService.thread_history(thread_id, checkpoint_ns, limit)`: move the
   description-matching resolution out of `threads/router.py::get_subagent_state`. For
   `checkpoint_ns == "tools:<tool_call_id>"` resolve to the subgraph checkpoint and return
   `[{ "values": {"messages": [...]}, "checkpoint": {"checkpoint_ns": <requested>,
   "checkpoint_id": ...}, "metadata": {}, "next": [], "tasks": [] }]`. Echo the *requested*
   namespace: the SDK keys its seed cache by it. No `checkpoint_ns` → keep returning `[]`
   (the SDK's root history pass wants pregel task internals we don't reconstruct; an empty
   page leaves the default `tools:<toolCallId>` namespace in place, which is exactly the key
   the scoped seed then asks for).
2. Delete `GET /threads/{id}/subagents/{tool_call_id}/state` and its helpers.
3. Web: delete `loadSubagentHistory`/`subagentMessages`/`fetchedSubagentHistory`,
   `onOpen`/`fallbackMessages`/`requestedInitialHistory`/the error-card effect, and
   `subagent.test.tsx`. `useMessages(stream, subagent)` is now the only source.
4. Verify: refresh an idle thread with a finished subagent, open the card, expect one
   `POST /history` with `checkpoint.checkpoint_ns`, messages rendered. Also an
   interrupted thread (live path, unchanged) and a running one.

### B. Render `BaseMessage` directly, delete `LCMessage` (≈ −150 lines)

- Delete `lib/utils/lc-messages.ts` and every `baseMessageToLC` call; type props as
  `BaseMessage[]`.
- `getTextContent` → `.text`; `getReasoningContent` → `contentBlocks` `reasoning` blocks
  (keep the DeepSeek `additional_kwargs.reasoning_content` fallback only if a DeepSeek
  thread still needs it under v3 — memory says reasoning now reaches the wire as content
  blocks; check one thread before deleting); `getFileAttachments` → `image`/`file` blocks.
- Replace the dual type checks with the core guards; drop every camelCase fallback.
- `LocalToolCall` → the SDK's own `ToolCallWithResult` (`{id, call, result, aiMessage,
  index}` — same fields, exported from `@langchain/langgraph-sdk`); keep `state` as a
  derived helper.

### C. One tool-step view for root and nested (≈ −250 lines)

- One pure `pairToolCalls(messages, liveToolCalls?)` in `message-helpers.ts` used by both
  `ConversationBody` and `SubAgentConversation`; the latter takes
  `useToolCalls(stream, subagent)` for live status. Delete `SubAgentConversation`'s private
  copies (`getTextFromMessage`, `parseToolName`, `getToolOutputContent`, inline prefix
  matching).
- Extract `<ToolStep tc nested? approval? />` from `conversation-body.tsx:337-470` and
  `subagent.tsx:150-215`. Root passes the approval footer + `McpAppWidget`; nested passes
  neither.
- Delete the "task call whose subagent is not discovered" branch
  (`conversation-body.tsx:402-440`). `SubagentDiscovery.seedFromCheckpointMessages` runs on
  every hydrate and `tool-started` for `task` upserts live, so `subagents.has(tc.id)` is
  always true for a `task` call once the message exists. Confirm with one refresh + one
  live run, then remove. (This is the only visible behaviour change in A–C, and it should
  be unreachable.)
- Move the `chainByOwner` turn grouping (`conversation-body.tsx:191-224`) into a pure
  `groupTurns()` with a unit test. It stays: the framework has no "consecutive AI messages
  form one chain" notion.

### D. Page glue (≈ −120 lines)

- `useThrottledValue` ×2: the v1 root store already coalesces writes per macrotask
  (`RootMessageProjection.#pendingMessages`), `ConversationBody` is memoised and
  `MessageResponse` is memoised on `children`. Re-run `web/scripts/measure-stream-memory.mjs`
  (:3100 vs a worktree) with the throttle removed; drop the hook if peak heap and
  main-thread CPU are within noise.
- HITL: drop the pre-id fallbacks — `pendingIdsAreReal`, the positional `{type}` decision
  form and `interruptId: null` path in `useHitlApprovals`. The checkpoint-keyed form has
  been the only writer since PR #307; the backend keeps accepting positional resumes for
  one release, the client no longer needs to emit them.
- `use-protocol-fetch.ts`: keep (domain 409 translation has no SDK equivalent), but rewrite
  the docstring — it still narrates the deleted `use-durable-run`.
- Replace the three `ai`/`@ai-sdk/react` type imports with local unions; remove both
  packages. Apply the knip list above (15 deps, `badge.tsx`, dead exports); add
  `@modelcontextprotocol/sdk` and `@modelcontextprotocol/ext-apps` to `package.json`.
- Comments that describe the previous architecture ("notified per SSE event",
  "legacy SSE", `@deprecated` `getType()` usage) go with their code.

### E. Optional design trims (not required by A–D)

- `SubAgentProgress` + `SynthesisIndicator` (subagent.tsx, ~80 lines): the progress bar
  duplicates the per-card status; "Synthesizing results…" duplicates the `ChainOfThought`
  "Working…" header. Removing both loses one bar and one line of italic text.
- `Reasoning` (228 lines, ai-elements copy with controllable state, auto-close timer,
  duration counter): could become a `ChainStep`-style collapsible (~60 lines). Loses the
  "Reasoned for N seconds" label and the 2 s auto-close.
- `ai-elements/prompt-input.tsx` (1,049 lines, vendored): out of scope for the
  conversation body; 11 of its 26 exports are used. Separate pass.

## Expected outcome

| | Today | After A–D |
| --- | ---: | ---: |
| Web chat-render lines in scope | ≈ 2,390 | ≈ 1,350–1,450 |
| Bespoke endpoints for the chat | 1 (`/subagents/{id}/state`) | 0 (`/history` becomes real) |
| Home-grown message shape | `LCMessage` | none (`BaseMessage`) |
| Tool-call pairings | 2 (root + nested) | 1 |
| `ai` / `@ai-sdk/react` | type-only deps | removed |

Not in scope and unchanged: the emitter contract (`agents/protocol/emit.py`), the
`tools`-channel overlay's existence (root `toolCalls` are not seeded by the SDK — file
upstream), `use-protocol-fetch` (domain 409s), `Conversation` (stick-to-bottom),
`ChainOfThought` / `ChainStep` primitives (the design).
