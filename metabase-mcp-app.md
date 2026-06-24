# auxilia × Metabase MCP — Integration Findings

Why a Metabase "MCP App" (interactive `visualize_query` chart) wouldn't render in auxilia — and the chain of fixes that got it there. Each fix only revealed the next layer.

## TL;DR

Rendering one interactive chart exercised **three independent subsystems**, and auxilia's "proxy everything server-side + render in a `srcdoc` sandbox" model collided with each:

1. **MCP capability negotiation** — servers gate UI tools behind a client capability the bundled SDK doesn't expose.
2. **MCP session lifetime** — Metabase binds artifacts (`sessionToken`, `query_handle`) to the MCP session; auxilia's per-request / per-call sessions destroyed them.
3. **Iframe origin** — the embed assumes a real `location.origin`; `srcdoc` gives `"null"`, which breaks its request-URL construction.

Claude Desktop sidesteps all three by holding one long-lived session and rendering on a real dedicated origin (`*.claudemcpcontent.com`).

Legend: **[BE]** backend (Python / MCP client) · **[FE]** frontend (Next.js / `@mcp-ui/client`) · **[MB]** Metabase's bundle/behavior.

## The chain, in the order it unravelled

### 1. [BE] Tool wasn't even listed

- **Symptom:** `visualize_query` absent from `list_tools`.
- **Cause:** MCP Apps gate UI-bearing tools behind the client capability `io.modelcontextprotocol/ui`. The SDK's `ClientSession.initialize()` hardcodes capabilities — no hook to add it.
- **Fix:** Monkeypatch `ClientSession.initialize` to advertise the UI capability (under both `extensions` and `experimental`). Also made `connect_to_server` follow `tools/list` pagination.
- **Files:** `app/mcp/client/initialize.py`, `app/main.py`, `app/mcp/servers/service.py`

### 2. [BE] Tool call crashed on output validation

- **Cause:** Recent MCP SDK validates a result's `structuredContent` against the tool's `outputSchema` and _raises_. Metabase's declared schema (`query`: base64 string) didn't match what came back → the call died.
- **Fix:** Same patch wraps `_validate_tool_result` to log, not raise.
- **Files:** `app/mcp/client/initialize.py`

### 3. [FE] App iframe never mounted

- **Cause:** `@mcp-ui/client` 6.1.0 threw an uncaught "Timed out waiting for sandbox proxy frame to be ready" under React StrictMode (Next.js dev double-mount).
- **Fix:** Bump to `@mcp-ui/client` 7.1.1 (PR #190). v7.0.0 was a no-op major; `AppRenderer` props unchanged.
- **Files:** `web/package.json`

### 4. [FE] Color parser crash

- **Cause:** `Unable to parse color from string: lab(100% 0 0)` — we passed Tailwind v4 `oklch()` theme vars via `hostContext`; the app's parser can't read CSS Color 4. `getComputedStyle` doesn't downconvert (Chrome re-serializes to `lab()`).
- **Fix:** Normalize each color through a **canvas 2D** round-trip → guaranteed `rgb()`.
- **Files:** `web/src/hooks/use-mcp-host-context.ts`

### 5. [BE][FE] App auth — 401 on its bootstrap

- **Cause:** The resource HTML embeds `window.metabaseConfig.sessionToken`, which Metabase binds to the MCP session. Our SDK closed each session with `terminate_on_close=True` → an HTTP `DELETE` that killed the session immediately, so the embedded token was _dead before the browser used it_.
- **Fix:** Pass `terminate_on_close=False` on the app paths (read-resource / call-tool); let Metabase expire by TTL. Also advertise `hostCapabilities` (`serverTools`/`serverResources`) + `hostInfo` on `AppRenderer`.
- **Files:** `app/mcp/servers/service.py`, `app/mcp/apps/router.py`, `web/src/app/(protected)/agents/[id]/chat/components/mcp-app-widget.tsx`

### 6. [BE] `query_handle` expired between tool calls

- **Cause:** The flow is `construct_query` → returns a `query_handle` → `visualize_query(query_handle)`. But `MultiServerMCPClient.get_tools()` opens a **new session per tool call** (confirmed in its docstring) — so the handle, minted in session A, was gone by session B.
- **Fix:** Persistent session per turn — split `Toolset.prepare()` (all DB work, in request scope) from `Toolset.open()` (one live session per server, held in an `AsyncExitStack` across the whole `astream`/`ainvoke`). HITL middleware moved into `_build_agent`. All DB work kept in `build` so it survives the streaming-response DB-session lifetime.
- **Files:** `app/agents/toolset.py`, `app/agents/runtime.py`, `app/mcp/client/factory.py`

### 7. [FE] App stuck on the "press Run" draft state

- **Cause:** The widget memoized `toolResult` but not `toolInput`; parent re-renders re-sent `toolInput` after the result arrived, resetting Metabase's app to "edited query — press Run."
- **Fix:** Memoize `effectiveToolInput` by content hash, like `toolResult`.
- **Files:** `web/src/app/(protected)/agents/[id]/chat/components/mcp-app-widget.tsx`

### 8. [FE][MB] "Question introuvable" → the real culprit: `Invalid base URL`

- **Trace:** Verified via Metabase's source (`getMcpDeserializedCard`, `useMcpApp`, `load-question.ts`): the query is fully _resolved_ (db 23, table 7460, fields by id), metadata loads (200). Yet `/api/dataset` never fired.
- **Cause:** The embed builds requests with `new URL(basename + "/api/dataset", location.origin)`. In a `srcdoc` iframe `location.origin` is the string `"null"`, and `new URL(anything, "null")` **throws regardless of basename** — so the data query can never be constructed.
- **How Claude works:** Renders the app on a **real dedicated origin** (`*.claudemcpcontent.com`, the spec's `McpUiResourceMeta.domain` field) → valid `location.origin`.
- **Fix:** Load the app via a `blob:` URL (inherits our origin → valid `location.origin`) instead of `srcdoc`, with a `srcdoc` fallback. _(render confirmed 2026-06-20 — see Status)_
- **Files:** `web/public/sandbox.html`

### 9. [BE] Surfacing the real errors (debug enablers)

- **Cause:** MCP tool errors came back as block-list `ToolMessage`s; the AI-SDK adapter only shows _string_ error text, so the UI masked everything as "Tool execution failed."
- **Fix:** Flatten error content to a string + log real MCP errors in `ToolErrorMiddleware`. (Plus temporary `[viz]` logging that let us decode the exact query — **to be removed**.)
- **Files:** `app/agents/tool_errors.py`, `app/mcp/client/tools.py`

## Three root insights

1. **Capability negotiation.** MCP servers withhold UI tools (and reject their calls) unless the client declares the MCP Apps UI capability during `initialize`. The bundled SDK doesn't expose this — hence the global patch.
2. **Stateful sessions.** Metabase binds the embed `sessionToken` and the `query_handle` to the MCP session. auxilia's per-request / per-call sessions destroyed them. The fix: one persistent session per turn, and don't `DELETE` sessions the browser still needs.
3. **Real origin, not `srcdoc`.** The embed assumes a valid `location.origin`. `srcdoc` gives `"null"`, which breaks its request-URL construction. Real hosts assign a dedicated origin; we approximate it with a `blob:` URL.

## Files touched

| File                                                                     | Change                                                                       |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `app/mcp/client/initialize.py` _(new)_                                   | Patch `ClientSession.initialize` (UI capability) + lenient output validation |
| `app/main.py`                                                            | Apply the patch at startup (lifespan)                                        |
| `app/mcp/servers/service.py`                                             | `tools/list` pagination; `terminate_on_close` param on `connect_to_server`   |
| `app/mcp/apps/router.py`                                                 | read-resource / call-tool use `terminate_on_close=False`                     |
| `app/mcp/client/factory.py`                                              | `terminate_on_close=False` on agent-runtime connections                      |
| `app/agents/toolset.py`                                                  | Split into `prepare()` (DB) + `open()` (persistent session)                  |
| `app/agents/runtime.py`                                                  | Open one MCP session per server across the run; HITL moved into build        |
| `app/agents/tool_errors.py`, `app/mcp/client/tools.py`                   | Surface/flatten real MCP tool errors; diagnostics                            |
| `web/package.json`                                                       | `@mcp-ui/client` → 7.1.1; pin `@modelcontextprotocol/ext-apps`               |
| `web/src/hooks/use-mcp-host-context.ts`                                  | oklch → rgb color normalization (canvas)                                     |
| `web/src/app/(protected)/agents/[id]/chat/components/mcp-app-widget.tsx` | Advertise `hostCapabilities`/`hostInfo`; memoize `toolInput`                 |
| `web/public/sandbox.html`                                                | Load app via `blob:` URL (real origin) instead of `srcdoc`                   |

## Status

Steps 1–8 verified working end-to-end (2026-06-20): the `visualize_query` chart renders, data path included — the `blob:`-URL origin fix held.

**One dev-only caveat (not one of the 9):** under React StrictMode (Next dev default), the double-mount makes `@mcp-ui/client` 7.1.1's `AppRenderer` tear down its host↔app transport mid-connect → `protocol.ts "Not connected"` + the app stuck on Metabase's "press Run" placeholder. The chart renders fine in production builds. 7.1.1 is the latest release (no upstream fix yet); the decision (2026-06-20) is to keep StrictMode on and revisit on the next `@mcp-ui/client` release. See the note by `<AppRenderer>` in `mcp-app-widget.tsx`.

Cleanup still owed: remove the temporary `[viz]` logging in `app/mcp/client/tools.py`.
