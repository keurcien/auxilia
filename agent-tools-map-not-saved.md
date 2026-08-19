# Investigation: tools shown in the UI but never saved to the agent config

**Date**: 2026-08-18
**Status**: FIXED 2026-08-19 — see "Fix (implemented)" below. Behavior tests in
`web/src/app/(protected)/agents/[id]/components/agent-tool-list.test.tsx`
(replaces the original repro test file) and
`backend/tests/agents/mcp_servers/test_service.py` (`_sync_tools` merge).

## Symptoms

1. Adding an OAuth MCP server to an agent: after consent the tools load in the
   UI, but the tools map is never persisted → agent "not configured", chat runs
   without the tools.
2. An already-bound MCP server gains new tools: they appear (enabled) in the
   UI, but are never saved into the binding's tools map → chat never gets them.

## Root cause

A three-way disagreement introduced by the explicit-save editor refactor
(read/edit split + atomic `PUT /agents/{id}/config`):

1. **The runtime excludes unknown tools.** `_assemble_agent_tools`
   (`backend/app/agents/toolset.py:162-181`) only binds tools whose name is in
   the saved map with `always_allow` / `needs_approval`; a missing key — or a
   `tools=null` map — means the tool is silently dropped.
2. **The UI defaults unknown tools to enabled.** `statusFor`
   (`web/.../agent-mcp-server.tsx:61-68`) falls back to `"always_allow"` for
   any tool not in the map, so the editor renders exactly the opposite of what
   the runtime will do.
3. **The draft map is only seeded when it is still `null` AND the editor is in
   edit mode.** `seedIfUnsynced` early-returns on `readOnly`
   (`agent-mcp-server.tsx:93-106`), and `handleSeedTools`
   (`agent-tool-list.tsx:68-79`) only fills a binding whose `tools === null`.
   `PUT /agents/{id}/config` → `set_for_agent`
   (`backend/app/agents/mcp_servers/service.py:104`) intentionally writes the
   map *exactly as the client sends it* — no discovery, no merge.

### Symptom 1 walkthrough (OAuth)

The natural flow is: add server (draft binding `tools: null`) → **Save** →
`onSaved` flips the page back to read mode (`agent-detail.tsx:51`) → card
shows NOT CONNECTED and still renders the **Connect** button in read mode
(`agent-mcp-server.tsx:261-277`) → consent → poll fetches and displays tools →
`seedIfUnsynced` bails on `readOnly` → nothing is dirty, nothing saved. DB
keeps `tools=null`, which the runtime treats as zero tools.

The old per-link endpoints did handle this: `create_or_update` runs
`_sync_tools` server-side after checking OAuth authorization, and
`POST /agents/{id}/mcp-servers/{id}/sync-tools` exists
(`backend/app/agents/router.py:250`) — but the explicit-save frontend never
calls either (no `sync-tools` reference anywhere in `web/src`). The post-OAuth
discovery path was lost in the refactor.

### Symptom 2 walkthrough (new tools on the server)

Binding map is non-null (e.g. `{search: always_allow}`), server now exposes
`create_page`. The UI lists `create_page` as enabled (the `statusFor`
fallback), but the seed only fills null maps, so the draft never changes:
Save stays disabled, and even a save triggered by another edit sends the stale
map. `set_for_agent` writes it verbatim; the runtime keeps excluding the new
tool.

## Reproduction

The original repro tests asserted the buggy behavior (read mode + `tools:
null` kept `"tools": null` in the payload; a stale map never dirtied the
form). They were replaced by the behavior tests for the fixed semantics:

`cd web && npx vitest run src/app/\(protected\)/agents/\[id\]/components/agent-tool-list.test.tsx`

- edit mode + never-synced binding → seed fills the draft, form dirty,
  payload carries the full map.
- edit mode + stale map → merge-seed adds new tools, preserves curated
  statuses, drops vanished keys, dirties the form.
- read mode + null/stale map → self-heals via sync-tools on view; an
  up-to-date map never writes.
- read mode + OAuth connect poll → persists via sync-tools after consent.

## Fix (implemented 2026-08-19)

- **Merge-seed** (`agent-tool-list.tsx` `handleSeedTools`,
  `agent-mcp-server.tsx` `seedFromFetched`): whenever a connected server's
  tools are fetched in edit mode, the fetched list becomes the draft map's key
  universe — curated statuses preserved, new tools added as `always_allow`,
  vanished tools dropped. An out-of-date map dirties the form (honest UNSAVED
  chip); an up-to-date one is left identical (no spurious dirty). Fixes
  symptom 2 and the edit-mode half of symptom 1.
- **Read mode self-heals stale maps** (`agent-mcp-server.tsx`
  `persistIfStale`): whenever tools are fetched in read mode — on page load
  for connected servers (incl. no-auth / API-key, which have no Connect
  action) and after the OAuth connect poll — the frontend compares the
  fetched list with the saved map and, when they disagree (never synced, or
  the server gained/lost tools), calls
  `POST /agents/{id}/mcp-servers/{id}/sync-tools` and mirrors the saved map
  into the agents store (`onToolsPersisted` → `onBindingPersisted` →
  `updateAgent`). An up-to-date map is a no-op, so plain viewing stays
  write-free. Fixes symptom 1 and symptom 2 in read mode.
- **Backend `_sync_tools` now merges instead of clobbering**
  (`backend/app/agents/mcp_servers/service.py`): server tool list is the key
  universe, existing statuses win, new tools default to `always_allow`. Makes
  the sync-tools endpoint safe to call on a curated binding.
- **Connected pill**: each MCP server card in the agent editor now shows
  CONNECTED (success tokens) / NOT CONNECTED, replacing the
  not-connected-only badge.

### Residual gaps (accepted)

- The map only updates when someone *opens the agent page* (read-mode
  self-heal or edit + Save). Agents that are only ever run via triggers or
  Slack keep a stale map until a page view; runtime-side sync during
  `Agent.build` would close that but is a bigger change.
- A read-mode sync by a user whose credentials see a narrower tool list (e.g.
  restricted OAuth scopes) persists that narrower list (statuses preserved
  for surviving tools) — same property as the pre-refactor
  `create_or_update` discovery.
- The staleness check compares tool-name sets only; the sync-tools POST is
  skipped when names match, so a pure description change never writes (tool
  descriptions aren't stored in the map at all).
