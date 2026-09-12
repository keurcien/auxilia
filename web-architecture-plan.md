# Web architecture plan — the five candidates from the 2026-08-31 review

*Written 2026-09-12 against `main` @ `202e67a`. Source: the `improve-codebase-architecture` HTML report
(`architecture-review-20260831-110242.html`, produced on `main` @ `35758cc`). The report predates PRs
#305–#324, which rewrote the whole chat path (worker-native Agent Streaming Protocol, `@langchain/react`
views, subagent HITL, deepagents 0.7). This plan re-derives each candidate against the tree today and
turns the surviving ones into PR-sized steps with tests and acceptance criteria.*

---

## Implementation log (2026-09-12, branch `refactor/web-architecture`, uncommitted)

Everything below shipped in **PR #325** as one commit per stage (squash on merge). The §4
slicing table, the "PR:" lines under each candidate and the §6 sequencing are the plan *as
written*, kept so the commits can be read against it — not remaining work. Stages 6–9 (resource
slices) were run as three parallel passes; stage 10 reconciles the ESLint allowlist. Deviations
from the plan as written:

- **§2** `useStream`'s hydration reads (`getState` / `getHistory`) go through the SDK client's own
  caller, not the `fetch` option. `useThreadSession` passes the same transport as
  `callerOptions.fetch`, so every protocol request now shares `protocolFetch`. Before this, those
  reads relied on the browser's default same-origin cookie behaviour.
- **§2** `toApiError` also accepts an axios-shaped plain object (`{ status, response: { data } }`):
  existing component tests reject with that shape, and it keeps not-yet-migrated call sites honest.
- **§3** The hook test with a scripted transport *works* under vitest + jsdom (the spike passed):
  hydration, the parked first message, the `model_unavailable` 409 gate and the stale-error rule are
  all covered end to end. The `stale_interrupt` gate is covered at the `useProtocolFetch` level, since
  responding requires a hydrated interrupt.
- **§3** `run` exposes both `status` and `isLoading`; the body needs the SDK's `isLoading`
  unchanged while a run is interrupted.
- **§4** Slices were regrouped by shared files: A = mcp-servers + sandboxes (+ mcp-apps),
  B = agents + tags + teams + users + invites + auth, C = triggers + models. All three landed in
  one pass, so the allowlist was created and then deleted within the same branch; the boundary
  rule is unconditional in `eslint.config.mjs`.
- **§4** Server components (`triggers/[id]/page.tsx`, `mcp-servers/[id]/page.tsx`, `agents/[id]/page.tsx`)
  pass the request cookie as `{ cookie }` to the resource function instead of reaching for axios headers.
- **§4** New type files `src/types/users.ts` and `src/types/auth.ts`; `Team` and `PersonalAccessToken`
  moved out of dialog components and are re-exported from there for untouched importers.

### Result

| Measure | Before (`main` @ 202e67a) | After |
| --- | --- | --- |
| Vitest files / tests | 12 / 62 | 30 / 166 |
| `tsc --noEmit` | clean | clean |
| ESLint (base) | 12 problems, 1 error | 11 warnings, 0 errors (all pre-existing) |
| Axios call sites outside `src/lib/api/` | 100 in 44 files | 0 |
| Files importing `@/lib/api/client` outside `src/lib/api/` | 50 | 0 (lint-enforced) |
| Chat page (`[threadId]/page.tsx`) | 512 lines, 9 `useState`, 3 refs, 1 timer, 3 API calls | 162 lines, none of those |
| Module-level mutable poll state | `lastPolledAt`, `pollSeq` in a hook | store state, tested |
| Resource modules | — | agents, auth, invites, mcp-apps, mcp-servers, models, runs, sandboxes, teams, threads, triggers, users |

Not done here: the manual QA checklist in §3 (needs a browser on `PORT=3100`) and a production
`next build` (the dev server on `:3000` owns `.next`). Per-stage patches for splitting the branch
into the PRs of §6 are in the session scratchpad (`stages/stage-1.patch` … `stage-6.patch`; stage 6
is the three resource slices plus the allowlist removal).

## 0. Where the five candidates stand today

| # | Candidate (report wording) | Report verdict | Status on `main` today | Plan |
| --- | --- | --- | --- | --- |
| 1 | Delete the transcript encoding nobody reads | Strong | **Landed** by #313 / #315 / #322 (see §1) | Close-out only: tracker + docs |
| 2 | One decoder at the transcript seam | Strong | **Half obsolete.** The un-converter and the 13 dual reads are gone; the shallow axios seam and two hand-rolled raw-fetch paths remain | Rescoped (§2) |
| 3 | A thread session module for run state | Strong | **Live.** `use-durable-run.ts` is gone, but the page still owns orchestration with 9 `useState`, 3 refs, a 4 s race, 3 API calls; the poller still has module-level mutable state | Full plan (§3) |
| 4 | A data-access module per resource | Worth exploring | **Live.** 100 axios call sites in 44 files, two dedupe implementations, cache-sync duty in callers | Full plan, sliced (§4) |
| 5 | Put the test surface at the interface | Speculative | **Live**, trivial. `shouldCloseAddToolDialogAfterServerAdded` still exists; the dialog test already asserts the behaviour | One small PR (§5) |

The top recommendation of the report ("1 → 2, give the transcript one owner") is done on the backend
half. The web half of "one owner" is now candidate 3, which is where this plan puts its weight.

---

## 1. Candidate 1 — landed. Close it out.

### Evidence it landed

- `backend/app/threads/serialization.py` no longer exists. `deserialize_to_ui_messages`, `_convert_part`,
  `_build_tool_metadata_map` are gone from the tree (only a stale `__pycache__` remains, gitignored).
- `langchain-ai-sdk-adapter` is gone from `backend/pyproject.toml`; the `Message` / `*MessagePart`
  models are gone from `backend/app/models.py`.
- `GET /threads/{id}` (`backend/app/threads/router.py:23-42`) no longer opens the checkpoint at all; its
  docstring records why (16 MB shipped twice per page load).
- One encoder: `backend/app/agents/protocol/messages.py` — `serialize_message` (stream) and
  `serialize_message_preview` (snapshots, bounded tool results since #322). Consumers: `protocol/emit.py`
  (worker), `protocol/service.py` (`thread_state`, `thread_history`, `message`), and Slack via
  `protocol/wire.py::decode_event`. Tested in `tests/agents/protocol/test_messages.py` and `test_emit.py`.
- No cross-module import of a `_private` serializer remains (`_serialize_lc_message` is gone).

### What is left

1. **Tracker.** `backend-cleanup-todo.md:598` still lists P3-7 as
   "Thread reads into the service; O(1) subagent state; **one history encoding**; stable message ids".
   Split the line: mark the encoding half `[x]` with a pointer to #313/#322; keep the rest open
   (thread reads into the service, O(1) subagent state, stable message ids, and the
   `POST /threads` agent-permission gate noted under it).
2. **CLAUDE.md.** The repository-structure entry for `threads/router.py` still says
   "Thread CRUD & history". History lives in `agents/protocol/` now. One-line fix.
3. **Guard the deletion.** Add a small test in `tests/agents/protocol/test_messages.py` that asserts
   `app.threads` imports nothing from `app.agents.protocol.emit` (import-boundary check via
   `importlib`/`sys.modules`), so the seam can't silently grow back a second encoder. Optional; cheap.

**PR:** `docs(backend): close the history-encoding half of P3-7` — docs only, no version bump.

---

## 2. Candidate 2 — rescoped: make the two transports explicit and test the seam

### What the report described vs. what exists now

The report's problem was `toSdkMessages()` undoing the axios camelCase conversion so the LangGraph
SDK could read the transcript, plus 13 dual-shape reads. After #312/#313/#315:

- The SDK hydrates from `GET /threads/{id}/state` and `POST /history` through its own `fetch`
  (`useStream({ apiUrl, fetch })`), which bypasses axios entirely. No un-converter exists.
- `message-helpers.ts` reads typed `BaseMessage` objects from `@langchain/core` (`tool_calls`,
  `tool_call_id`, `additional_kwargs` are the SDK's own field names, not dual reads). The only
  legitimately snake_case client-side write is `tool_call_id` in the `input.respond` payload.

So the "decodeTranscript module" the report asked for exists in substance: it is `message-helpers.ts`
(14 KB, 12 exports, tested in `message-helpers.test.ts`). What is still shallow is the *transport*
seam beneath it.

### Remaining problems (with evidence)

| Problem | Where |
| --- | --- |
| Two hand-rolled raw-fetch paths exist *because* axios would camelize protocol payloads — same-origin guard + `credentials: "include"` built twice | `web/src/hooks/use-protocol-fetch.ts:41-60`, `web/src/lib/api/thread-messages.ts:17-29` |
| The axios interceptor camelCases 200 bodies but not error bodies; `getApiErrorMessage` exists for this, yet five call sites read `error.response.data.detail` by hand | `lib/api/errors.ts`; `invite/[token]/page.tsx:66`, `settings/create-token-dialog.tsx:61`, `settings/sandbox-dialog.tsx:188-192`, `settings/workspace-models.tsx:28-29`, plus `axios.isAxiosError` scattered |
| `PRESERVE_KEYS_FIELDS = ["tools", "arguments"]` is a global hidden rule every caller must know | `lib/api/client.ts:21` |
| The interceptor has no tests at all | `client.ts` — 0 test files |
| The transcript decode module lives under a route folder although four components consume it; a hook in `src/hooks/` (candidate 3) importing from `app/(protected)/…/[threadId]/` would be a smell | `app/(protected)/agents/[id]/chat/[threadId]/message-helpers.ts` |

### Target design

```
web/src/lib/api/
  client.ts          axios instance + case conversion (unchanged contract, now tested)
  errors.ts          ApiError { status, code?, detail, body } + isApiError() + getApiErrorMessage()
  protocol.ts        NEW — PROTOCOL_BASE_URL, protocolFetch(input, init): same-origin guard +
                     credentials, no case conversion. decodeProtocolRejection(status, body)
                     → { kind: "model_unavailable" | "stale_interrupt", detail } | null
  thread-messages.ts fetchThreadMessage() built on protocolFetch (drops its own URL/credentials code)

web/src/hooks/use-protocol-fetch.ts
                     thin: protocolFetch + run bookkeeping (markThreadRunning / requestPoll) +
                     decodeProtocolRejection → handler callbacks. No URL parsing of its own.

web/src/lib/transcript/          NEW — message-helpers.ts split by concern, tests move along
  message.ts        getReasoning, getFileAttachments, getStructuredContent, getToolMetadata,
                    sanitizeToolIdentifier
  tool-calls.ts     ToolCallView, pairToolCalls, getToolStepState, getMcpAppInfo
  interrupts.ts     splitInterrupts, sameNamespace, claimsInterrupt, findSubagentInterrupt,
                    extractHitlToolNames
  chains.ts         ChainStepData, groupChains
```

`ApiError` is produced once, in a response *error* interceptor in `client.ts`: it reads `status`,
`detail` (4xx only, as `getApiErrorMessage` already rules), and the machine-readable `error` /
`model_id` keys the backend's `ModelUnavailableError.body()` emits. Everything downstream catches
`ApiError`, never `AxiosError`. This is also the error contract the resource modules of §4 will throw.

### Steps

1. Add `client.test.ts`: request bodies snake_cased, `tools` / `arguments` preserved both ways,
   `FormData` untouched, `params` snake_cased, 200 bodies camelCased, error bodies normalised to
   `ApiError`. This freezes the current behaviour *before* anything moves.
2. Add `protocol.ts` with `protocolFetch` + `decodeProtocolRejection` and unit tests for the 409
   mapping (`model_unavailable`, `stale_interrupt`, unknown 409, non-409). Rewrite
   `use-protocol-fetch.ts` and `thread-messages.ts` on top of it.
3. Replace the five hand-rolled `response.data.detail` reads with `getApiErrorMessage` / `isApiError`.
   Remove direct `axios` imports from components (`workspace-models.tsx`, `sandbox-dialog.tsx`).
4. Move `message-helpers.ts` to `lib/transcript/` (four files), update the four importers
   (`page.tsx`, `conversation-body.tsx`, `subagent-card.tsx`, `tool-step.tsx`), move the test.
   Mechanical; no logic change.

### Acceptance

- `grep -rn "credentials: \"include\"" web/src` hits `lib/api/protocol.ts` only.
- `grep -rn "response?.data?.detail\|response.data.detail\|isAxiosError" web/src --include=*.tsx` is empty.
- `client.ts`, `protocol.ts`, `errors.ts` each have a test file; `npm test` green; pre-commit
  `eslint.precommit.mjs --fix` clean on touched files.

**PRs:**
`refactor(web): one protocol transport and typed API errors` (steps 1–3) ·
`refactor(web): move transcript helpers to lib/transcript` (step 4).

---

## 3. Candidate 3 — `useThreadSession`: one module answers "what is this thread doing"

### Current state (all in `web/src/app/(protected)/agents/[id]/chat/[threadId]/page.tsx`, 512 lines)

Run lifecycle is still spread across six places, none independently testable:

| Concern | Where it lives today | Why it is hard to test |
| --- | --- | --- |
| Thread metadata (model, effort, archived, viewer role, model availability) | `page.tsx:47-53`, fetched at `:320` and re-fetched at `:179` | Page-local `useState` ×5 |
| Failed-run error rehydration + staleness rule | `page.tsx:52-54, 378-401`; `rehydratedErrorStale` set in `handleSubmit`, `respondToInterrupt`, `handleRegenerate` | A ref mutated from three callbacks; the rule ("a submit invalidates a slow fetch") is only in comments |
| Pending first message from the starter page | `page.tsx:344-358`: `Promise.race(hydrationPromise, setTimeout 4 000)` | Timing race written inline |
| Interrupt identity hold | `page.tsx:89-97` (`heldInterrupts` state-during-render trick) | Invisible invariant |
| Pre-run 409 gates | `use-protocol-fetch.ts:63-91` → page callbacks; stale interrupt does `window.location.reload()` | Side effect chosen inside a fetch wrapper |
| Active-run bookkeeping | `onCompleted` and `handleStop` call `useActiveRunsStore.getState().requestPoll()`; `use-protocol-fetch` calls `markThreadRunning` | Fine, but page-owned |
| Poller | `hooks/use-active-runs.ts:24-27` — module-level `lastPolledAt` / `pollSeq`; `applyFinishedRuns` writes into `threads-store` and `trigger-runs-store` | No test can reset the poller; cross-store writes happen from a hook file |

The SDK already owns reattach/replay (`useStream` with `threadId`), so the module is smaller than the
report sketched: it is the layer *around* `useStream`, not a replacement for it.

### Target interface

```ts
// web/src/lib/thread-session/use-thread-session.ts
export function useThreadSession(args: {
  threadId: string;
  agentId: string;
  transport?: ThreadSessionTransport;         // defaults to the real one; tests inject a scripted one
  onStaleInterrupt?: () => void;              // page decides what to do (today: reload)
}): ThreadSession;

export type ThreadSession = {
  meta: {
    status: "loading" | "ready";
    modelId?: string; reasoningEffort: string | null;
    agentArchived: boolean; modelAvailable: boolean; viewerRole: "admin" | null;
    header: ChatHeaderData;                     // what setCurrentChat receives today
  };
  run: {
    status: "idle" | "streaming" | "interrupted";
    error: string | null;                       // stream.error merged with the rehydrated last-run error
  };
  transcript: {
    messages: BaseMessage[]; toolCalls: ToolCallView[];
    subagents: AnyStream["subagents"]; todos: Todo[];
    stream: AnyStream;                          // stable handle the subagent cards project from
  };
  hitl: {
    interrupt: Interrupt | null; nestedInterrupts: Interrupt[];
    hitlToolNames: Set<string> | null; pendingToolCalls: ToolCallView[];
    decisions: Record<string, HitlDecision>; recordDecision(id, d): void;
  };
  actions: {
    send(message: PromptInputMessage): void;    // builds content parts, clears stale error
    regenerate(): void; stop(): void;
    respond(response: HitlResponse, interruptId: string | null): void;
    recheckModel(): Promise<void>;
  };
};

export type ThreadSessionTransport = {
  fetch: typeof fetch;                          // what useStream gets (protocolFetch + bookkeeping)
  readThread(threadId): Promise<ThreadRead>;    // GET /threads/{id}  → threads resource module (§4)
  listRuns(threadId): Promise<RunSummary[]>;    // GET /threads/{id}/runs
};
```

### Internal structure — keep the invariants pure

The hook is thin; the rules live in pure, tested functions:

```
web/src/lib/thread-session/
  use-thread-session.ts     the hook: useStream + wiring; ~150 lines
  session-reducer.ts        pure state machine for the page-local state:
                            events = threadLoaded | runsLoaded | userActed | streamErrored |
                                     rejected(model_unavailable|stale_interrupt) | completed
                            → { meta, run.error, staleGuard }
  pending-message.ts        submitPendingAfterHydration(hydrationPromise, submit, { capMs }) —
                            exactly-once, cap-bounded
  interrupt-hold.ts         holdInterrupts(prev, next) — the key/identity rule from page.tsx:89-97
  build-content.ts          promptMessageToContent(message) — the text/image/file part builder
  session-reducer.test.ts · pending-message.test.ts · interrupt-hold.test.ts · build-content.test.ts
  use-thread-session.test.tsx   renderHook with a scripted transport (see risk below)
```

Invariants that become tests (each is a bug class the page has already had):

1. A rehydrated last-run error is **dropped** once the user sends, responds or regenerates, even if
   the `/runs` fetch resolves afterwards.
2. A pending starter message is submitted **exactly once**, after hydration settles or after the cap.
3. Interrupt list identity is stable while the interrupt key is unchanged.
4. Positional vs addressed HITL payload follows `pendingIdsAreReal` (all call ids present).
5. A `model_unavailable` rejection sets `meta.modelAvailable=false` **and** `run.error`;
   `stale_interrupt` invokes `onStaleInterrupt` and sets no error.
6. `completed` and `stop()` request one poll each; `run.start` marks the thread running.

### Poller half (`use-active-runs.ts`)

Move `lastPolledAt` / `pollSeq` into `active-runs-store` as state, and move `applyFinishedRuns` into
a store action `applyPollResult(runs, polledAt)` that fans out to `threads-store.setLastRunStatus`
and `trigger-runs-store.setRunStatus`. The hook keeps scheduling (visibility, backoff, trigger watch
window) and calls `runsResource.listActive(recentSeconds)` (§4). Tests reset with
`useActiveRunsStore.setState(initial)`; the supersede rule ("an older in-flight poll cannot overwrite
a newer one") becomes a store test.

### Page after

`page.tsx` renders: one `useThreadSession` call, `useChatHeaderStore` sync from `meta.header`, the
four banners (admin / archived / model unavailable / not configured), `ConversationBody`,
`ChatPromptInput`. No `api.*`, no `useRef`, no `setTimeout`. Target ≈ 200 lines.

### Risk — testing around `useStream`

`useStream` (`@langchain/react` ^1.0.33) reads `/state` and `/stream/events` through the injected
`fetch`. A scripted `fetch` returning fixture JSON and a hand-built SSE `ReadableStream` should run
under vitest + jsdom (Node 20 provides `ReadableStream`/`TextEncoder`), but this is **unverified**.
Mitigation, in order:

1. Spike first (half a day): `renderHook(() => useStream({ fetch: scripted }))` against a canned
   `/state` snapshot. If it hydrates, the hook test is real and cheap.
2. If not, `vi.mock("@langchain/react")` with a controllable fake `useStream` for the hook test, and
   rely on the pure-module tests for the invariants. The page already treats `stream` as an opaque
   handle, so the fake is small.

Either way the six invariants are tested at the pure layer; the spike only decides how much of the
wiring is covered.

### Manual QA checklist (run on `PORT=3100`, never the dev server on `:3000`)

send · stop mid-stream · regenerate · root HITL approve/reject · subagent HITL approve in place ·
stale interrupt (approve the same request from Slack first) → reload · model disabled by admin →
banner + "Check again" · starter page → pending first message lands once · failed run → error
rehydrated on reopen, gone after next send · archived agent banner · admin viewing another user's
thread (read-only) · sidebar running badge appears on send and clears on completion · trigger run
history "Failed" marker after a failed firing.

**PRs:**
`refactor(web): useThreadSession owns run state, the chat page renders` (hook + pure modules + page) ·
`refactor(web): active-runs poller state moves into the store` (poller half; independent, can go first).

---

## 4. Candidate 4 — one resource module per domain concept

### Evidence today

- **100 axios call sites in 44 files** (`grep -rn "api\.\(get\|post\|patch\|delete\|put\)" web/src`).
  Same route hand-typed in several places: `/mcp-servers/${id}/list-tools` ×2, `/mcp-servers/official` ×2,
  `/agents/${id}` ×3, `/threads/${id}` ×3, `/sandboxes` ×2, `/teams/` ×3, `/mcp-servers` ×3.
- **Two dedupe implementations**: `agents-store.ts:19-56` (chained `inflight` with re-fetch queuing),
  `mcp-servers-store.ts:21-45` (`fetchInFlight`). `triggers-store.fetchTriggers` has none — two mounts
  before `isInitialized` flips fire two requests.
- **Cache-sync duty in callers**: `agents-store` exposes only local mutators (`updateAgent`,
  `removeAgent`), so `agent-editor.tsx:150-198`, `agent-tags-panel.tsx:63`, `archived-agent-dialog.tsx:28-41`
  each do the HTTP call *and* remember to mirror it into the store. This is the class the tools-map bug
  lived in. `mcp-servers-store` and `triggers-store` already do it the right way (mutation owns the
  cache update) — the pattern exists, it just isn't universal.
- **Error handling decided per site**: `console.error` + local toast/dialog, five hand-rolled `detail` reads (§2).
- **Untyped responses**: `page.tsx:320-340` reads `data.thread.modelId` etc. off `any`; `ThreadRead`
  (`{ thread: ThreadResponse; viewerRole }`) has no TypeScript type.

### Target design

```
web/src/lib/api/resources/
  agents.ts        list, get, create, saveConfig, patch, archive, restore, permanentDelete,
                   isReady, permissions(get/put), teams(get/put), tags (list/create/patch/delete)
  mcp-servers.ts   list, get, create, patch, delete({detachAgents}), reset, official, listTools,
                   agentsUsing, connections(list/delete), connectionTest endpoints
  threads.ts       list(page), read(id) → ThreadRead, create, rename, delete, listRuns(id)
  runs.ts          listActive(recentSeconds)
  triggers.ts      list, get, create, patch, delete, run, threads(id), schedulePreview
  models.ts        list, enable/disable, default(put/delete), providers…
  sandboxes.ts     list, create, patch, delete({detachAgents}), agentsUsing, secretHint
  users.ts         list(page, search), roleCounts, patchRole, patchTeam, delete
  teams.ts         list, create, patch, delete
  invites.ts       list, create, delete, read(token), accept
  auth.ts          providers, signin, signout, me, setupStatus, setup, tokens(list/create/delete)
```

Rules for a resource module:

- Plain `async` functions, typed request/response from `src/types/*`, built on `api` from `client.ts`.
  **No React, no zustand, no toasts.** Throws `ApiError` (§2). One file per backend router prefix.
- Query-string knowledge stays here (`detach_agents=true` is built in one place, not in
  `workspace-sandboxes.tsx:120` and `mcp-servers-store.ts:68`).
- Stores import resource modules, never `client.ts`. A mutation that must update a cache is a **store
  action** (`agentsStore.saveConfig(id, cfg)` calls `agentsResource.saveConfig` then `updateAgent`).
  Components call the store action; they never mirror an HTTP result into a store by hand.
- One in-flight helper, `lib/api/once.ts` — `createOnce<T>(load: () => Promise<T>)` returning
  `{ run(): Promise<T>, reset() }` — replaces both hand-rolled dedupes and gives `triggers-store` one.
  Tested once.

### Enforcement — make the seam a lint rule, not a convention

Add to `eslint.config.mjs` (base config, so `npm run lint` and `next build` enforce it):

```js
{
  files: ["src/**/*.{ts,tsx}"],
  ignores: ["src/lib/api/**"],
  rules: {
    "no-restricted-imports": ["error", {
      paths: [{ name: "@/lib/api/client", message: "Import a resource module from @/lib/api/resources instead." },
              { name: "axios", message: "Catch ApiError from @/lib/api/errors; never AxiosError." }],
    }],
  },
},
```

Land it in the **first** §4 PR with a `files` allowlist listing the not-yet-migrated files; every
subsequent slice deletes its files from the allowlist. The allowlist is the migration's progress bar.

### The fake

The report's rule: a seam is only real once a second adapter exists. Here the second adapter is
`vi.mock("@/lib/api/resources/<name>")` in vitest — a component test mocks *named functions with typed
signatures*, not URLs. `add-agent-tool-dialog.test.tsx:13-17` currently mocks `api.get` and answers
every GET with the same array; after migration it mocks `mcpServers.list` and `sandboxes.list` separately,
which is both more honest and shorter. No hand-written fake class is needed.

### Slicing (one PR per row, each independently shippable)

| Slice | Resource(s) | Call sites moved | Why this order |
| --- | --- | --- | --- |
| 4a | `threads`, `runs` + lint rule with allowlist + `once.ts` | `page.tsx` ×3, `chat/page.tsx`, `rename-thread-dialog`, `app-sidebar` delete, `threads-store` ×2, `use-active-runs` | Prerequisite for §3's transport |
| 4b | `mcp-servers` | `connect-servers-dialog` ×2, `agent-mcp-server` ×4, `agent-tool-list`, `add-agent-tool-dialog`, `mcp-server-detail`, `connected-users-panel` ×2, `use-connection-test` ×4, `mcp-servers/page`, `add/page`, `add/custom/page`, `[id]/page`, `use-delete-mcp-server`, `mcp-servers-store` ×5 | Most duplicated routes |
| 4c | `agents` (+ tags, permissions, teams-binding) — adds store actions `saveConfig`, `archive`, `restore`, `permanentDelete`, `setTag` | `agent-editor` ×3, `agent-permissions-panel` ×6, `agent-tags-panel` ×2, `archived-agent-dialog` ×2, `new-tag-dialog` ×2, `[id]/page`, `threads/page`, `chat/page`, `use-agent-connection-status`, `agents-store` | Closes the tools-map bug class |
| 4d | `triggers`, `models`, `sandboxes`, `auth.tokens` | `triggers-store` ×5, `trigger-runs-store`, `triggers/[id]/page`, `next-runs-card`, `models-store`, `workspace-models` ×6, `workspace-sandboxes` ×4, `sandbox-dialog` ×2, `settings/page` ×2, `create-token-dialog`, `agent-tool-list` sandboxes | Settings surface |
| 4e | `users`, `teams`, `invites`, `auth` | `users/page` ×9, `invite-dialog`, `new-team-dialog` ×2, `auth/page` ×2, `invite/[token]` ×2, `setup/page` ×2, `user-store` ×2 | Leaf pages, lowest churn |
| 4f | Remove the allowlist; `client.ts` is importable from `lib/api/**` only | — | Done |

Each slice: add the module + a test file that asserts method/path/params per function (an axios
mock adapter or `vi.spyOn(api, "get")`), move the call sites, delete the files from the allowlist,
run `eslint.precommit.mjs --fix` on touched files.

**PR titles:** `refactor(web): threads and runs resource modules, import boundary for the API client`,
then `refactor(web): mcp-servers resource module`, … `refactor(web): drop the API-client import allowlist`.

---

## 5. Candidate 5 — inline the dialog predicate

### Evidence

- `web/src/app/(protected)/agents/[id]/lib/mcp-server-assignment.ts` — 6 lines, one export
  (`shouldCloseAddToolDialogAfterServerAdded`), one call site (`add-agent-tool-dialog.tsx:178`).
- `mcp-server-assignment.test.ts` — 3 cases on a one-line predicate.
- `add-agent-tool-dialog.test.tsx` already asserts the behaviour where the user meets it:
  "adds the server to the draft and closes when it was the last one".

### Steps

1. Inline `availableServerIds.length === 1 && availableServerIds[0] === addedServerId` at the call site.
2. Delete `lib/mcp-server-assignment.ts` and its test; the `lib/` directory under `agents/[id]/` is then
   empty — delete it.
3. Add the negative case to the dialog test: with two available servers, adding one calls `onAddServer`
   and does **not** call `onOpenChange(false)`. That is the only assertion the deleted test had that
   the dialog test lacks.

### The other `lib/` extractions, checked against the same deletion test

- `mcp-servers/lib/mcp-server-create-form.ts` — 92 lines, two consumers (`add/page.tsx`,
  `add/custom/page.tsx`), 151-line test. Concentrates real form logic. **Keep.**
- `lib/triggers/schedule.ts` — 8.4 KB cron/timezone math, tested. **Keep.**
- `mcp-servers/lib/use-connection-test.ts` — a hook with 4 API calls; migrates in slice 4b, not a §5 case.

**PR:** `chore(web): inline the add-tool dialog close predicate`.

---

## 6. Sequencing (as planned — executed as the seven commits of PR #325)

```
PR 0a  docs(backend): close the history-encoding half of P3-7                       [§1]  docs
PR 0b  chore(web): inline the add-tool dialog close predicate                       [§5]  ~30 lines
PR 1   refactor(web): one protocol transport and typed API errors                   [§2 steps 1–3]
PR 2   refactor(web): move transcript helpers to lib/transcript                     [§2 step 4]
PR 3   refactor(web): threads and runs resource modules, import boundary            [§4a]
PR 4   refactor(web): active-runs poller state moves into the store                 [§3 poller]
PR 5   refactor(web): useThreadSession owns run state, the chat page renders        [§3 core]
PR 6–9 refactor(web): <resource> resource module                                    [§4b–4e]
PR 10  refactor(web): drop the API-client import allowlist                          [§4f]
```

Dependencies: PR 5 needs PR 1 (`protocolFetch`, `ApiError`), PR 2 (imports from `lib/transcript`),
PR 3 (`threads.read`, `threads.listRuns`), PR 4 (store-owned poll state). PR 0a, 0b, 1, 2, 3, 4 are
mutually independent and can be opened in parallel. PRs 6–9 are independent of each other and of PR 5.

Every PR title above is Conventional-Commits shaped because release-please takes the squash title
as the `main` commit. `refactor` appears in the changelog; `chore`/`docs` do not bump.

---

## 7. Guardrails that outlive the plan

- **Import boundary** (§4) in the base ESLint config — the one rule that keeps the seam from eroding.
- **Two transports, named**: anything reading LangGraph-shaped payloads goes through `protocolFetch`;
  anything reading our own DTOs goes through a resource module. `client.ts` is not a public import.
- **Store actions own cache sync.** A component never pairs an HTTP call with a manual store mutation.
- **Pure before hook.** Timing and ordering rules (stale error, hydration cap, interrupt hold, poll
  supersede) live in pure modules with tests; hooks wire them.
- **Extraction rule** (§5): a `lib/` module must either have two consumers or concentrate logic that
  cannot be asserted at the component. Otherwise inline it and test at the component.

## 8. Not reopened

Nothing here touches the backend design review's "do not reopen" list (`backend-cleanup-todo.md:705`):
no DDD, no queue replacement, no package split. The backend half of candidate 1 is closed rather than
extended. Replacing zustand or axios is out of scope: the plan changes who is allowed to call them,
not what they are.
