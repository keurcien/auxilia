# Part 3 — Worker-native Agent Streaming Protocol (implementation plan)

**Date**: 2026-09-02 · **Status**: implemented 2026-09-02 (all phases, one
change set, uncommitted) — see *Implementation notes* at the end.
**Context**: follows #309 / PR #310 (client quick fixes), PR #311 (protocol
backend facade), PR #312 (frontend migration to `@langchain/react`).

## Goal

Replace the legacy LangGraph SSE event log with **native Agent Streaming
Protocol events emitted by the worker** via LangChain 1.3's
`astream_events(..., version="v3")`, and give Slack a protocol-consuming
adapter. End state:

```
worker: astream_events(v3) ──thin wire serializer──▶ Redis log (protocol events,
                                                     seq/event_id at publish)
                                   ├─▶ POST /threads/{id}/stream/events: filter + relay
                                   └─▶ Slack adapter: protocol → chat_stream / blocks
```

Deleted at the end: `app/agents/protocol/translate.py` (the read-side
translator and its determinism invariant), `SlackStreamAdapter`
(`app/agents/stream.py`), the legacy SSE wire format, and the legacy stream
endpoints. The durable-run spine (queue, claim, finalize, reaper, `_END`
sentinel marker, checkpoint recovery) is **not** redesigned.

## Verified findings (empirical, 2026-09-02, on this repo's env)

All spikes were run with `uv run python` against the installed stack
(langchain 1.3.17 / langgraph 1.2.11 — see version table below).

1. **`astream_events(input, config, version="v3")` emits the protocol
   grammar natively.** It returns `langgraph.stream.run_stream.
   AsyncGraphRunStream` (note: the call itself must be awaited before
   iterating) with projections: `messages`, `values`, `tool_calls`,
   `lifecycle`, `subagents`, `subgraphs`, `interrupts`, `interrupted`,
   `extensions`, `output`, `abort`. Iterating `stream.messages` yields
   `AsyncChatModelStream` objects whose event iterator produces exactly:
   `{'event': 'message-start', 'role': 'ai', 'id': …}` →
   `{'event': 'content-block-start', 'index': 0, 'content': {...}}` →
   `{'event': 'content-block-delta', 'index': 0, 'delta':
   {'type': 'text-delta', ...}}` → `content-block-finish` →
   `message-finish` — byte-identical to what the facade's hand-rolled
   translator produces and PR #312's client consumes.
2. **The raw iterator yields protocol envelopes but not the message
   grammar**: `async for ev in stream` gives `{method, params: {namespace,
   ...}}` dicts, but the `messages`-method payloads are still
   `(chunk, metadata)` tuples. The wire serializer must take the grammar
   from the `messages` projection (or serialize the per-message event
   iterators), not from the raw envelopes.
3. **Checkpointing is unaffected by the streaming API.** Same run consumed
   via v3 with a checkpointer bound: checkpoint written per superstep with
   the identical schema (`channel_values`, `channel_versions`, `id`, `ts`,
   `updated_channels`, `v`, `versions_seen`), `BaseMessage` objects in
   `channel_values.messages`, `metadata.step` present. **No checkpoint
   migration; historical threads hydrate unchanged.**
4. **Interrupts keep the #307 contract.** A `langgraph.types.interrupt()`
   under v3 lands in the checkpoint's `pending_writes` as
   `('__interrupt__', [Interrupt(id='<32-hex xxh3>')])` — the exact shape
   `app/agents/hitl.py` (`pending_interrupt`, `build_resume_command`,
   `_INTERRUPT_ID_RE`) keys on. Checkpoint-keyed approvals and stale-resume
   409s work unchanged.
5. (From the Part 2 work — client-contract facts are embedded in
   `backend/app/agents/protocol/*` module docstrings.) The web client:
   flips `isLoading` only on a root lifecycle **`running`** event; drops
   event extension fields in its ToolCallAssembler (MCP artifacts must ride
   *inside* `tool-finished.output` as `{content, artifact}`); treats
   message-less `values` snapshots as a non-message refresh (keep stripping
   `messages`/`files` at publish); binds subagent namespaces
   (`tools:<task-id>` ≠ tool-call id) by first-human-message text unless
   lifecycle causes provide better linkage; needs the string-content human
   echo (see PR #312's first-message fix) unless v3 emits the input turn.

## Dependency status (installed → latest, checked 2026-09-02)

| Package | Installed | Latest | Notes |
| --- | --- | --- | --- |
| langchain | 1.3.17 | — | v3 event streaming available ≥1.3 (`transformers` middleware ≥1.3.2) |
| langchain-core | 1.6.0 | — | |
| langgraph | 1.2.11 | — | `AsyncGraphRunStream` lives here |
| langgraph-checkpoint | 4.2.0 | — | |
| **langgraph-checkpoint-postgres** | **3.0.4** | **3.1.2** (2026-08-07) | see below |
| deepagents | 0.5.6 | 0.7.x planned | upgrade planned (`framework-upgrade-assessment.md`) |

**checkpoint-postgres 3.0.4 → 3.1.2** (do this upgrade first or alongside
Phase 1): the 3.1.x line moved to **delta-based channel-value storage**
(3.1.0 promoted it stable; 3.1.2 fixed a plain-value seed-discovery bug in
delta history traversal) and 3.1.1 **scoped checkpoint namespace matching to
segment boundaries** — directly relevant to our subagent state lookups by
`checkpoint_ns` (`/threads/{id}/subagents/{tool_call_id}/state`) — plus an
optional `omit_expired` read parameter. Release notes report no breaking
changes; the checkpointer runs its own internal migrations
(`checkpoint_migrations` table) via `setup()` — verify our
`get_checkpointer` path runs setup on boot, and test reads of *pre-upgrade*
rows after upgrading on the dev DB (memory: the dev DB is shared across
branches — see `alembic-multi-branch-stamping`).

## Implementation plan

### Phase 0 — spike (blocker questions, ~half a day)

Run a real `create_deep_agent` graph (a subagent-bearing auxilia agent)
through `astream_events(v3)` and answer:

1. **deepagents compatibility**: do `stream.subagents` / namespaced events
   appear, and is the namespace shape compatible with what the web client's
   `SubagentDiscovery` binds on (`tools:<task-id>`)? If v3's lifecycle
   events carry a `cause: {type: "toolCall", tool_call_id}` (the protocol
   spec supports it), the first-human-message binding trick and the
   namespaced-values message can both be dropped.
2. **Resume path**: `astream_events(Command(resume=...), config, version="v3")`
   — the worker resumes runs this way (`RunDB.command`). Verify it executes
   and streams like `astream` does.
3. **Provider quirks**: DeepSeek `additional_kwargs.reasoning_content` →
   does v3 surface it as `reasoning` blocks natively? Anthropic thinking
   blocks? Tool-call chunk assembly on OpenAI/Anthropic/DeepSeek/Gemini.
4. **Input echo**: does v3 emit the input human message on any channel? If
   not, keep PR #312's values-echo behavior at the serializer (string
   content, non-empty id, once per namespace/role/id).
5. **Volume**: events per token vs the legacy log — re-size
   `run_settings.max_events` (MAXLEN) accordingly.

### Phase 1 — dependency upgrades (separate PRs)

- `langgraph-checkpoint-postgres` 3.0.4 → 3.1.2 (see notes above; verify
  `setup()` migration on dev DB, then old-row reads + subagent-ns lookups).
- deepagents 0.5.6 → 0.7 (already planned; Phase 0 will say whether it is a
  prerequisite for correct v3 subagent projections).

### Phase 2 — worker-native emission (backend PR)

- **Wire serializer** (new `app/agents/protocol/emit.py` or similar):
  consume `astream_events(v3)` — raw envelopes for `values`/`lifecycle`/
  `tools`/`interrupts` channels (already `{method, params}`-shaped) plus the
  `messages` projection for the message grammar — and produce wire `Message`
  envelopes `{type: "event", event_id, seq, method, params}`. Assign
  `seq`/`event_id` **at publish** (monotonic counter per run is fine now —
  ids are stored, not derived; the read-side determinism problem
  disappears). Keep publishing through `BufferedEventPublisher`
  (`app/agents/runs/events.py`) — the log stores one JSON event per entry.
  Preserve the publish-side policies from the facade: strip
  `messages`/`files` from `values` payloads, wrap MCP artifacts into
  `tool-finished.output`, emit root lifecycle `started` **and `running`**,
  map terminal statuses (`cancelled`→`completed`, unknown→`failed`),
  `input.requested` from the interrupts projection.
- **Run format tag**: `RunDB.format` column (`legacy` | `protocol`,
  default `legacy`, alembic migration); worker writes `protocol` for new
  runs behind a settings flag (`RUN_EVENT_FORMAT=protocol`) so rollout is a
  config flip.
- **Terminal semantics**: keep the log's `_END` field as the
  format-agnostic terminal marker (`subscribe`, reaper, and
  `wait_for_terminal` in `app/agents/runs/{events,service}.py` key on it) —
  `finalize` publishes the protocol terminal lifecycle event *with*
  `_END: 1` instead of the legacy sentinel for protocol-format runs.
- **Endpoints dual-read** (`app/agents/protocol/service.py`): per run,
  `format == "protocol"` → filter + relay stored events (stamping nothing);
  `legacy` → existing translator path. The 1h log TTL bounds the mixed
  window to about an hour after deploy.
- **Error containment**: the legacy path relied on
  `LangGraphStreamAdapter` swallowing stream exceptions into an `error`
  event and the worker sniffing it (`worker._ERROR_EVENT_PREFIX`) — port
  both to the serializer (emit lifecycle `failed` with the root-cause
  message; worker detection becomes format-aware or moves to the
  serializer's return value).
- **Contract tests**: `tests/agents/protocol/test_translate.py` encodes the
  wire grammar the client needs (message lifecycle, tools channel, values
  trimming, human echo, dedupe scoping, terminal rules) — re-point these at
  the native serializer's output so the client contract survives the swap.

### Phase 3 — Slack protocol adapter (integration PR)

Replace `SlackStreamAdapter` with a protocol-event consumer in
`app/integrations/slack/consumer.py`:
- `messages` channel `text-delta`s → `chat.appendStream` (reasoning deltas
  excluded, as today);
- `tools` `tool-started` → tool labels / Slack thinking steps
  (`agents.sessions.setStatus`);
- `input.requested` → approval blocks directly (today's checkpoint read on
  `end: interrupted` becomes unnecessary, but keep it as fallback);
- root lifecycle terminal → today's end-of-run behavior.
Pair with the 2026 Slack agent primitives in the same PR if desired:
`agent_session_stopped` event → `RunService.cancel`, streaming Block Kit
blocks for tool cards (see references).

### Phase 4 — deletions & docs

- Delete `app/agents/protocol/translate.py` + its tests' legacy-encoder
  harness, `SlackStreamAdapter` and `decode_sse_blocks`' Slack use,
  `encode_synthetic_ai_message_sse`'s legacy path, and the legacy stream
  endpoints `POST /threads/{id}/runs/stream` + `GET
  /threads/{id}/runs/{run_id}/stream` (KEEP `/runs/invoke`, `POST /runs`,
  run CRUD, `/runs/active`, `/runs/{id}/cancel` — durable-runtime surface;
  the protocol client's `stop()` calls the cancel route, the sidebar polls
  `/runs/active`).
- Update `app/agents/runs/SPEC.md` ("Event protocol" section) and
  `CLAUDE.md`; drop the legacy notes from `app/agents/protocol/__init__.py`.

### Verification (existing harnesses, all in `web/scripts/`, gitignored)

- `verify-protocol-chat.mjs` — hydration, streamed reply, endpoints on the
  wire, console errors.
- `verify-first-message.mjs` — the fresh-thread first-message race
  (run ≥5 iterations; this exercised the human-echo semantics).
- `measure-stream-memory.mjs` — heap/CPU benchmark (baseline: protocol
  facade = 54.6MB peak / 3.1s script CPU on the standard essay prompt).
- Manual pass: HITL approval on an agent with `interrupt_on` tools (web +
  Slack), Slack streaming, reattach mid-run (reload during a long run),
  trigger firing, `/runs/invoke` with `output_schema`.

## Invariants that must survive (learned the hard way in Parts 1–2)

- At-most-once run execution; no retries (see `runs/SPEC.md`).
- Client `isLoading` requires root lifecycle `running` (not just `started`).
- MCP artifacts inside `tool-finished.output` (`{content, artifact}`) —
  client drops event extension fields.
- `values` events without `messages`/`files`; human input echoed once
  (string content + non-empty id) unless v3 provides the input turn.
- Unknown terminal status → `failed`, `cancelled` → `completed`.
- `seq` must be JS-safe (< 2^53) and monotonic; `event_id` unique — both
  now trivially satisfied by publish-time assignment.
- The frontend needs **no changes** for Phase 2/4 — its contract is the
  wire format, which is preserved by the contract tests.

## References

- Agent Streaming Protocol spec (CDDL is normative; `js/`+`py/` generated
  types): https://github.com/langchain-ai/agent-protocol/tree/main/streaming
- LangChain event streaming (v3 API, projections, transformers):
  https://docs.langchain.com/oss/python/langchain/event-streaming and
  https://docs.langchain.com/oss/python/langchain/streaming
- Background: https://www.langchain.com/blog/token-streams-to-agent-streams
  · examples: https://github.com/langchain-ai/streaming-cookbook
- Client stack consumed by our frontend: `@langchain/react` 1.0.33 /
  `@langchain/langgraph-sdk` 1.10.0 —
  https://github.com/langchain-ai/langgraphjs/tree/main/libs/sdk-react
- checkpoint-postgres releases:
  https://pypi.org/project/langgraph-checkpoint-postgres/ ·
  https://github.com/langchain-ai/langgraph/releases
- Slack agent platform (for Phase 3): agent sessions / stop button /
  `agent_session_stopped` —
  https://docs.slack.dev/changelog/2026/08/20/agent-updates/ · streaming
  blocks & MCP client —
  https://slack.dev/slack-developer-changelog-recap-april-june-2026/ ·
  agent context — https://docs.slack.dev/changelog/2026/07/02/app-context/
- In-repo: `streaming-memory-assessment.md` (original diagnosis + measured
  wins) · `backend/app/agents/protocol/` (facade; module docstrings carry
  the reverse-engineered client contract) · `backend/app/agents/runs/SPEC.md`
  (durable runtime) · `framework-upgrade-assessment.md` (deepagents 0.7).


## Implementation notes (2026-09-02)

Everything above landed as one change set (Phases 2–4 together, Phase 1 for the
checkpointer). Where the implementation deviates from the plan, and why:

- **No `RunDB.format` column / `RUN_EVENT_FORMAT` flag / dual-read.** All phases
  ship together, so a format tag would have been dead on arrival. The mixed
  window (a run in flight during the deploy, ≤1h of legacy-format log) is
  handled by tolerant decoding instead: `wire.decode_event` returns `None` for a
  pre-protocol SSE entry and every reader skips it; the `_END` marker is
  format-agnostic so such a run still terminates.
- **`event_id`/`seq` are still derived at read time**, from the Redis entry id
  (`wire.seq_for_entry`; one event per entry, so `event_id` *is* the entry id).
  Publish-time stamping would have needed a per-run counter shared between the
  worker and `finalize` (which also runs from the reaper and the expired-log
  path). Both invariants hold: JS-safe, monotonic across a thread's runs,
  unique ids, identical across reopened sessions.
- **The terminal lifecycle is published only by `RunService.finalize`** (as the
  log's `_END` entry, carrying `RunDB.error` on `failed`). The emitter never
  emits a terminal, and a graph failure propagates out of `Agent.stream`
  instead of being swallowed into an `error` event — the worker's existing
  exception path finalizes the run. Exactly one terminal, from one source.
- **Slack keeps the checkpoint read for approvals.** `input.requested` carries
  the HITL payload (tool names/args) but not the tool-call ids the Block Kit
  `block_id`s need; `pending_approval_requests(checkpoint)` stays the source.
  The terminal *status* comes from the durable record (the protocol folds
  `cancelled` into `completed`; Slack must stay silent on a Stop).
- **Phase 0 answers.** (1) deepagents 0.5.6 subagents stream under
  `tools:<task-id>` with a lifecycle `started` carrying `graph_name` and
  `cause: {toolCall, tool_call_id}` — but `@langchain/langgraph-sdk` 1.10's
  `SubagentDiscovery` still binds by the first human message text, so the
  namespaced-values first-human snapshot is kept (cause is forwarded too).
  deepagents 0.7 is **not** a prerequisite. (2) `Command(resume=…)` under v3
  streams like `astream`. (3) Under v3 the persisted AIMessage of a streaming
  provider is the bridge-assembled message: content is a **v1 content-block
  list** with `output_version: "v1"` (providers convert back themselves; the
  history endpoint renders it). Provider reasoning already reaches the wire:
  langchain-core 1.6's best-effort `content_blocks` turns DeepSeek's
  `additional_kwargs.reasoning_content` into a `reasoning` block and keeps
  tool-call chunks intact (verified against `chunks_to_events`; a custom
  "deepseek" translator was tried and dropped as redundant), and
  Anthropic/Gemini have registered translators. (4) v3 does not emit the input
  human message;
  the values-based echo is kept. (5) Volume: one `messages` event per token plus
  a few per superstep, no per-token state snapshots — `RUN_MAX_EVENTS` left at
  1,000.
- **Phase 1.** `langgraph-checkpoint-postgres` 3.0.4 → 3.1.2 (its migration 9
  adds `checkpoint_writes.task_path`); alembic `b7e2f4a9c1d3` re-runs
  `setup()`. Applied to the shared dev DB; pre-upgrade rows of the 25 newest
  threads read back.
- **Verification run.** Backend: 1025 tests, ruff, mypy clean; the new
  `tests/agents/protocol/test_emit.py` drives a real `build_runnable` graph
  (subagent via `task`, HITL interrupt + resume, MCP artifact) through v3.
  Web: `verify-protocol-chat.mjs` (streamed reply, only protocol endpoints, 0
  console errors) and `verify-first-message.mjs` 5/5 against the dev UI.
  Not rerun: `measure-stream-memory.mjs` (client wire grammar unchanged from
  Part 2), Slack streaming/HITL and `/runs/invoke` manual passes.
