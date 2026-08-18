# MCP Python SDK v2 migration assessment

*Investigated 2026-08-17. Current state: `mcp==1.26.0`, `langchain-mcp-adapters==0.3.0`, `httpx==0.28.1`.*

> **STATUS UPDATE (2026-08-17): implemented.** The migration is done on the working tree
> (uncommitted): `mcp==2.0.0`, langchain-mcp-adapters **removed**. New modules:
> `app/mcp/client/connection.py` (v2 `Client` opening — UI extension via `advertise()`,
> per-instance lenient validation, replaces `initialize.py` monkeypatches + `MultiServerMCPClient`)
> and `app/mcp/client/langchain_tools.py` (MCP→LangChain tool conversion, replaces
> `load_mcp_tools`). `auth.py` rewritten on httpx2: the copied 401 discovery flow is deleted —
> `initiate_authorization` is now a 401-probe that lets the SDK's own `async_auth_flow` run,
> with a one-shot `_recover_registration_context` retry preserving the TikTok quirks
> (path-aware ASM discovery + public-client DCR negotiation). Task-hosted session lifecycle and
> `ReconnectingSession` kept (v2's streamable HTTP transport still uses anyio task groups —
> same-task enter/exit constraint confirmed in v2 source). 598 tests pass; verified end-to-end
> against a live v2 MCPServer over streamable HTTP (modern + legacy handshakes, artifact shape,
> `is_error`→ToolMessage path); backend boots with the mounted `MCPServer` answering `/mcp`.
> Remaining real-server verification: Metabase MCP Apps (v2 advertises the UI capability under
> `extensions` only — v1 patch also used `experimental`), Notion/Supabase OAuth flows,
> and the Google Sheets `tools/list` latency re-measurement.
>
> **Post-implementation fixes (same day):**
> 1. *BigQuery: "expected a 401 challenge, got HTTP 200".* Some servers accept an
>    unauthenticated `initialize` and only 401 business calls, so a real probe never triggers
>    the SDK's discovery branch. `initiate_authorization` now pumps `async_auth_flow` by hand
>    (`_drive_auth_flow`) and answers the probe with a **synthetic 401** — the probe never hits
>    the wire (regression-guarded in tests); only the discovery/DCR requests do.
> 2. *SEP-2468 issuer byte-compare rejects Google's own metadata* (PRM `authorization_servers`
>    normalizes to `…google.com/`, ASM issuer is `…google.com`). Shimmed with a
>    trailing-slash-tolerant `validate_metadata_issuer` in `auth.py`; upstream fix is open but
>    unmerged ([python-sdk#3013](https://github.com/modelcontextprotocol/python-sdk/pull/3013)) —
>    drop the shim when it ships. Verified live against the real BigQuery MCP server: full
>    discovery + `OAuthAuthorizationRequired` with a correct accounts.google.com authorize URL
>    (scope from PRM, offline+consent, RFC 8707 resource).
>
> Cosmetic note: the SDK's `async_auth_flow` logs our intentional `OAuthAuthorizationRequired`
> as `ERROR OAuth flow error` (with traceback) on every authorization initiation — harmless,
> but worth a log filter if it gets noisy.
>
> **Toolset session scaffolding — verified empirically on v2 (2026-08-18):**
> 1. *Task-hosting still required*: entering a v2 `Client` in one task and exiting from another
>    raises `RuntimeError: Attempted to exit cancel scope in a different task` (the transport
>    still runs an internal anyio task group). `_open_sessions`' task-per-connection hosting stays.
> 2. *`ReconnectingSession` was silently broken on v2 and is now fixed*: the v1 dead-transport
>    signatures (`anyio.ClosedResourceError`/`BrokenResourceError`) no longer reach the caller —
>    the v2 dispatcher collapses every request touching a dead transport (in-flight AND later
>    sends, indistinguishably) into `MCPError(code=CONNECTION_CLOSED)`, which the proxy
>    deliberately never retried. Result: after a server drop, the server was lost for the rest
>    of the run. Fix (preserves at-most-once): a `CONNECTION_CLOSED` call is NOT retried (it may
>    have executed server-side; it surfaces as an error ToolMessage), but marks the session dead
>    so the NEXT call reconnects *before* sending. Verified live: kill server → in-flight call
>    errors → server restarts → next call reconnects and succeeds. (Note: in the
>    single-task `connect_to_server` paths a dying transport instead cancels the enclosing scope
>    — per-request connections die with their request, so no handling needed there.)
>
> **Cleanup (2026-08-18):** `connectivity._open_session` removed. `connect_to_server` now
> yields the bare v2 `Client` (auth resolution folded into `_resolve_transport_kwargs`),
> and callers list tools explicitly via `list_all_mcp_tools` — the MCP App
> read-resource/call-tool paths no longer pay an unneeded `tools/list` per request. The
> toolset session code (`_SessionSupervisor`, `ReconnectingSession`, task-hosted
> `_open_sessions`) is intentionally kept: v2's transport still requires same-task
> enter/exit and offers no reconnect.

## How the TypeScript SDK does OAuth — and what it means for us (2026-08-18)

Reviewed `modelcontextprotocol/typescript-sdk` (`packages/client/src/client/auth.ts`, 2.4k
lines, and `streamableHttp.ts`). The architecture is fundamentally different from Python's —
and it is **exactly the model our serverless flow needs**:

### The TS design

1. **`auth(provider, options)` is a standalone, public orchestration function** — documented as
   "a single entry point for all authorization functionality". It runs discovery (with cached
   `discoveryState`), SEP-2352 issuer binding, scope selection, CIMD/DCR registration, then
   branches on its inputs:
   - `options.authorizationCode` set → RFC 9207 `iss` validation → token exchange →
     `saveTokens` → returns `'AUTHORIZED'`;
   - stored refresh token → refresh → `'AUTHORIZED'`;
   - otherwise → builds the authorize URL + PKCE → `saveCodeVerifier` →
     `redirectToAuthorization(url)` → **returns `'REDIRECT'`**.

   There is **no blocking callback wait anywhere**. The flow is two-phase *by design*:
   begin (`auth()` → REDIRECT), then finish (`auth()` again with the code — surfaced as
   `transport.finishAuth(callbackParams)`).
2. **The provider is pure storage/policy — no HTTP in it.** `OAuthClientProvider` is
   `clientMetadata`, `clientInformation`/`saveClientInformation`, `tokens`/`saveTokens`,
   `saveCodeVerifier`/`codeVerifier`, `state?()`, `redirectToAuthorization` (which for a web
   backend can simply record the URL — nothing awaits a browser), plus hooks:
   `addClientAuthentication` (custom token-request auth), `invalidateCredentials(scope)`,
   `saveDiscoveryState`/`discoveryState` (persisted discovery, explicitly required to survive
   the redirect round-trip "with the same durability as codeVerifier"), `prepareTokenRequest`.
3. **401-catching is not how authorization *starts*.** The transport's 401 handler just calls
   the same public `auth()`; on `'REDIRECT'` it throws `UnauthorizedError` and the host drives
   the redirect + `finishAuth`. `state` validation is explicitly the host's job.
4. **`issuersMatch()` in TS is trailing-slash-tolerant** (`a === b` or slash-stripped equal) —
   the Python SDK's byte-compare (our Google shim) is the cross-SDK outlier, and TS even
   exposes `skipIssuerMetadataValidation` as an escape hatch.

### Mapping: our Python glue ↔ TS-native concept

| auxilia (`WebOAuthClientProvider`) | TypeScript SDK native |
| --- | --- |
| `initiate_authorization` + `_drive_auth_flow` (synthetic-401 pump) | `auth(provider, {serverUrl})` → `'REDIRECT'` |
| `_perform_authorization_code_grant` raising `OAuthAuthorizationRequired` | non-blocking `redirectToAuthorization(url)` |
| Redis `set_verifier` + state → (user, server) mapping | `saveCodeVerifier` + `state?()` provider hooks |
| `manual_exchange` (callback endpoint) | `auth(provider, {serverUrl, authorizationCode})` / `finishAuth` |
| `set_oauth_metadata` persistence + `_initialize` restore | `saveDiscoveryState` / `discoveryState` |
| `strip_client_id_for_basic_auth` (Notion) | `addClientAuthentication` hook |
| slash-tolerant issuer shim (Google) | `issuersMatch` (native) + `skipIssuerMetadataValidation` |
| `ensure_valid_token` | `auth()`'s refresh branch |
| `clear_user_server_data` | `invalidateCredentials(scope)` |
| `_initialize` expiry restore | upstream-acknowledged Python bug ([#1784](https://github.com/modelcontextprotocol/python-sdk/issues/1784)) |

### Verdict

- **Our architecture is validated**: the two-phase, storage-backed, never-block flow we built
  (v1 and v2 alike) is precisely what the TS SDK ships as its *only* model. Every piece of
  "custom" code we carry corresponds to a first-class TS provider hook.
- **The gap is purely Python SDK API surface**: Python only exposes the orchestration inline
  inside `async_auth_flow` (the httpx2 auth generator). Until it grows a public `auth()`
  equivalent, the options are (a) the synthetic-401 generator pump we ship now — reuses the
  SDK's orchestration wholesale, zero copied logic, proven live against BigQuery/Google; or
  (b) reimplementing an `auth()`-style orchestrator from `mcp.client.auth.utils` — which is
  the v1 copied-flow liability we deliberately deleted. **(a) stays.**
- **Upstream tracking**: [python-sdk#1743](https://github.com/modelcontextprotocol/python-sdk/issues/1743)
  ("Extract OAuth flow logic into reusable components for proxy use cases", open) is the ask
  for exactly this; worth a comment pointing at the TS `auth()` design + our use case.
  Related: [#1784](https://github.com/modelcontextprotocol/python-sdk/issues/1784) (stored-token
  expiry, our `_initialize` fix), [#3013](https://github.com/modelcontextprotocol/python-sdk/pull/3013)
  (trailing-slash issuer, our shim), [#2121](https://github.com/modelcontextprotocol/python-sdk/issues/2121)
  (pre-configured auth server URL, our TikTok path-aware seeding).
- **Free behavior worth knowing**: Python's `async_auth_flow` also handles
  `403 insufficient_scope` step-up by re-running authorization — with our grant override that
  surfaces mid-run as `OAuthAuthorizationRequired`, i.e. a scope-escalation 403 during an agent
  run correctly bubbles up as "re-authorize", matching TS's `'reauthorize'` default.
- When the Python SDK ships a public orchestrator, the migration is mechanical: delete
  `_drive_auth_flow`, call `authorize()`-equivalent from `initiate_authorization`, and
  `manual_exchange` collapses into the same call with `authorization_code=`.

## TL;DR

- **v2.0.0 is stable** (released 2026-07-28, alongside the 2026-07-28 protocol revision). v1 is in maintenance mode — security fixes only.
- **Hard blocker today: `langchain-mcp-adapters` does not support mcp v2.** [Issue #578](https://github.com/langchain-ai/langchain-mcp-adapters/issues/578) is open; the maintainer (mdrxy) said "planning to allocate time toward this very soon" on 2026-08-05. A complete community migration exists (`chrfsa/langchain-mcp-adapters`, branch `feat/mcp-v2`, 6 commits on top of 0.3.1, `mcp>=2.0.0,<3`) that we can use as a git dependency for local testing.
- **Yes, we can test locally** — plan below. Nothing about the migration requires infra changes; it's dependency + code changes only.
- **Glue-code payoff is real but smaller than hoped.** The two biggest v1-pain areas — the class-level `ClientSession` monkeypatches and the anyio session-lifecycle scaffolding — are exactly what v2 reworked, so they are likely to shrink or die. But the largest single file (`app/mcp/client/auth.py`, 478 lines) exists because we run OAuth *serverless* (Redis state + deferred callback), and v2 **keeps the blocking `redirect_handler`/`callback_handler` model**, so that file gets *rewritten*, not deleted.
- **Immediate action regardless of migration timing:** pin `mcp>=1.26,<2` and `langchain-mcp-adapters>=0.3.0,<0.4`. Nothing in our `pyproject.toml` has an upper bound today, so a routine `uv lock --upgrade` would pull mcp 2.0.0 and the backend would fail at import (`ImportError: cannot import name 'RequestContext' from 'mcp.shared.context'` — already reported by others on adapters ≤0.3.0).

## What v2 actually is

v2 is a ground-up rework, both for the 2026-07-28 spec and to fix v1's architectural problems. Key changes that matter to us:

| v2 change | Impact on auxilia |
| --- | --- |
| New first-class `Client` object (`async with Client(url)`) replacing the `streamablehttp_client` + `ClientSession` two-step | Simplifies `connectivity._open_session`; may let toolset drop its task-per-session scaffolding (needs prototyping — see below) |
| `httpx`/`httpx-sse` → **`httpx2`** | `WebOAuthClientProvider` extends `OAuthClientProvider`, which is now an `httpx2.Auth`. All our OAuth code and the plain-`httpx` refresh path in `ensure_valid_token` must move to httpx2. httpx2 coexists with httpx in the same venv, so langfuse etc. are unaffected |
| `FastMCP` → `MCPServer`; transport params move from constructor to `run()`/app methods | `app/mcp/router.py` (`auxilia_mcp`, currently stubs) + the `session_manager.run()` / `streamable_http_app()` mounting in `main.py` need porting — small |
| `mcp.types` → standalone `mcp-types` pkg (aliased); **camelCase → snake_case attributes** (`isError` → `is_error`, `inputSchema` → `input_schema`); `McpError` → `MCPError` | Mechanical sweep across `initialize.py`, `storage.py`, tests; adapters handle their own side |
| Dispatcher replaces the v1 receive loop; per-request JSON-RPC errors; timed-out requests actually cancel server-side; non-2xx surfaces as per-request errors | This is the fix for the class of failures behind `ReconnectingSession` and the ExceptionGroup unwrapping — needs verification, but the error paths are fundamentally restructured |
| GET stream: still started on `initialized`, **but** only if the server assigned a session id, with built-in auto-reconnect (`MAX_RECONNECTION_ATTEMPTS`); 2026-era servers replace standalone GET streams with `subscriptions/listen` entirely | The old 15s `tools/list` wedge (POST-only server holding the GET stream) is structurally gone for stateless/2026-era servers, still *possible* against 2025-era stateful servers. Re-measure with `scripts/diagnose_mcp_timing.py` |
| OAuth: `TokenStorage` stays a 4-method Protocol; `callback_handler` now returns `AuthorizationCodeResult(code, state, iss)`; RFC 9207 `iss` validation; `client_secret_post` now includes `client_id`; stricter `/token` auth; DCR sends `application_type` | `RedisTokenStorage` survives nearly unchanged. The provider subclass does not — see below |
| Experimental Tasks support removed; `create_connected_server_and_client_session` test helper removed; websocket transport dropped (adapters side) | Minor for us |

Docs: [migration guide](https://py.sdk.modelcontextprotocol.io/migration/) · [what's new](https://py.sdk.modelcontextprotocol.io/v2/whats-new/) · [v2.0.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0) · [pydantic's v2 beta article](https://pydantic.dev/articles/mcp-python-sdk-v2-beta)

## Glue-code inventory → verdict per item

Ordered by expected payoff. "Verify" = answerable only by the local spike.

### Likely deletable / big shrink

1. **`ClientSession` monkeypatches** (`app/mcp/client/initialize.py`, 164 lines, applied in `main.py:65`) — the UI-capability injection for MCP Apps (Metabase) rebuilds private capability assembly from five `_`-prefixed attributes, and `_make_lenient_validate` wraps the private `_validate_tool_result`. **These break on day one of v2** (the privates are gone) and must be redone regardless. v2's session/`_meta` rework and extension APIs are the natural home; verify whether `Client` exposes a capabilities/extensions hook. If yes: delete the whole module. If no: reimplement against v2 (smaller, since v2 has first-class extension APIs). The lenient-validation half may be *worse* in v2 (client-side schema validation of inbound traffic is now on by default) — check for a strictness knob.
2. **Session lifecycle scaffolding** (`toolset.py:198-370` — `_SessionSupervisor`, task-per-session `_open_sessions`, teardown-error demotion for `replaced` sessions; plus `runtime._setup`'s `return_exceptions=True` gather) — exists because v1's anyio cancel scopes must exit in the entering task. v2's `Client` is "construct, `async with`, call methods" and the dispatcher rework targets exactly this. **Verify with `scripts/repro_mcp_session_death.py` ported to v2**: if N clients can be opened/closed from a shared `AsyncExitStack` without the same-task constraint, ~170 lines die.
3. **`ReconnectingSession`** (`toolset.py:244-301`) — retry-once on `anyio.ClosedResourceError`/`BrokenResourceError`. v2's per-request error surfacing + GET-stream auto-reconnect + real cancellation may make dead-transport errors either not happen or arrive as typed per-request errors. Verify by killing the server mid-session (same repro script). Best case: delete; worst case: shrink to a typed-error retry.
4. **ExceptionGroup unwrapping** (`app/exceptions.py:root_cause`, `main.py:113-142` handler, `tool_errors.py` type-name fallback for empty-stringifying anyio errors) — v2's per-request error model should stop wrapping our `OAuthAuthorizationRequired` in nested task-group exceptions. Keep `root_cause` as defensive code, but the FastAPI `ExceptionGroup` handler and the empty-`str` workaround likely go.

### Rewritten, not deleted

5. **`WebOAuthClientProvider`** (`auth.py`, 478 lines) — the serverless redirect model (Redis PKCE state → raise `OAuthAuthorizationRequired(url)` → separate HTTP request completes via `manual_exchange`) is **still not what v2 offers**: v2 keeps blocking `redirect_handler`/`callback_handler`, just with a new `AuthorizationCodeResult` return. So the subclass survives, but every override must be redone:
   - `initiate_authorization` (the hand-copied 401 branch over `mcp.client.auth.utils` helpers) — verify those nine helpers still exist in v2; the docstring already says "keep in sync with the SDK flow on upgrades".
   - Overrides of private methods (`_initialize`, `_exchange_token_authorization_code`, `_refresh_token`, `_handle_token_response`, `_perform_authorization_code_grant`) — all against a rewritten base class, on httpx2.
   - Some quirk-fixes may now be upstream: v2 tightened token-endpoint auth (`client_secret_post` includes `client_id`, stricter `/token`), added `iss` validation and `application_type` at DCR. Re-test each: Notion Basic-auth `client_id` stripping, HTTP-201 tolerance, `none`-only DCR negotiation (TikTok), Supabase `client_secret_post` hardcodes, Google `access_type=offline&prompt=consent` (note v2 auto-requests `offline_access` with `prompt=consent` when supported — SEP-2207 — which may cover the Google case).
6. **`RedisTokenStorage`** (`storage.py`) — the `TokenStorage` Protocol is unchanged (same 4 methods, duck-typed). The `expires_at` absolute-time gap-fill, Google refresh-token carry-over, and verifier/state methods all remain needed. Only snake_case field access and any `OAuthToken` shape changes to sweep. **Survives ~intact.**

### Stays regardless

7. Serverless OAuth redirect model (Redis state, `OAuthAuthorizationRequired`, `/callback` endpoint) — our architecture, not SDK glue.
8. `terminate_on_close=False` plumbing (Metabase session-token binding) — v2's `streamable_http_client` still takes `terminate_on_close`.
9. Manual `tools/list` pagination with cycle guards (`connectivity._list_all_tools`) — v2 still exposes cursor pagination, no iterator.
10. Tool-name sanitization + `tool_name_prefix` handling (`toolset.py:23-59`) — a langchain-mcp-adapters concern, unchanged.
11. Per-server quirk hardcodes (Gmail scopes TODO, path-aware AS-metadata fallback) — retest, hopefully some die.

### Breaks silently — watch out

- **`tests/agents/test_toolset.py` (737 lines) uses duck-typed fakes with zero `mcp` imports** — it will pass on v2 even if the real session semantics changed. Same for most client tests. Only `test_auth.py`, `test_storage.py`, `test_initialize.py` exercise real SDK types. The spike must lean on *integration* smoke tests, not the unit suite.
- `tool_errors.py` assumes adapters ≥0.3.0 surface MCP `isError` results natively — re-verify against the adapters v2 port (`is_error` rename).
- `scripts/oauth.py`, `scripts/sheets.py`, `scripts/probe_metabase_mcp.py`, `scripts/repro_mcp_session_death.py` all import v1 API names and break; the last two are precisely the verification harnesses for the spike, so port them first.

## Migration effort estimate

| Work item | Size |
| --- | --- |
| Dependency bumps (mcp, adapters, +httpx2) & import sweep, snake_case sweep, `McpError`→`MCPError` | S |
| `app/mcp/router.py` + `main.py` FastMCP→MCPServer port | S |
| `initialize.py` patch: delete or reimplement on v2 extension APIs (Metabase MCP Apps must keep working) | M — gated on verify |
| `auth.py` rewrite on v2 base class + httpx2, re-test all provider quirks (Notion, Google, Supabase, TikTok, HubSpot) | **L — the bulk of the work** |
| Toolset lifecycle: prototype v2 `Client`; delete/shrink supervisor + `ReconnectingSession` | M |
| Integration smoke tests to replace duck-typed blind spots | M |
| Adapters: wait for upstream release or temporarily pin the community fork as a git source | external dependency |

Realistically ~1–2 weeks of focused work once adapters support lands, dominated by OAuth re-verification against real providers.

## Dropping langchain-mcp-adapters entirely (decision 2026-08-17)

Checked 2026-08-17: still no upstream ETA — issue #578 has no maintainer comment since Aug 5 ("planning to allocate time toward this very soon"), no maintainer migration PR exists (only dependabot bumps that can't pass CI, and the community fork awaiting approval), and 0.3.2 (Aug 6) is just the `<2` pin. Watch: [issue #578](https://github.com/langchain-ai/langchain-mcp-adapters/issues/578) and the [releases page](https://github.com/langchain-ai/langchain-mcp-adapters/releases).

Our actual adapters surface is two symbols in one file (`toolset.py`):

1. **`MultiServerMCPClient`** — used only as a config-dict → session factory (`client.session(name)`); `_SessionSupervisor`/`_open_sessions` already own the lifecycle. v2 replaces this natively: one `Client` per server, or **`ClientSessionGroup`** (kept in v2, `mcp/client/session_group.py`) which does multi-server connect/disconnect, tool aggregation, name-prefixing via `component_name_hook`, and `call_tool` routing. Nothing to miss here.
2. **`load_mcp_tools`** — the MCP-tool → LangChain-`StructuredTool` conversion (~400 lines in adapters' `tools.py`, MIT). This is the only real value we take, and the parts we depend on are enumerable:
   - `args_schema` from the tool's JSON `inputSchema` (passthrough, no pydantic model needed)
   - content conversion: `TextContent`/`ImageContent`/`EmbeddedResource`/`ResourceLink` → LC content blocks
   - `isError=True` → `ToolException` → `ToolMessage(status="error")` (what `tool_errors.py` relies on)
   - `structuredContent` → the tool **artifact** (what `app/mcp/client/tools.py` stamps `mcp_app_resource_uri` into — MCP Apps depend on this shape)
   - `_meta` copied into `tool.metadata` (what `_extract_mcp_app_resource_uri` reads)
   - `{server}_{tool}` name prefixing (we re-sanitize on top anyway)

   Pagination we already own (`connectivity._list_all_tools`). A replacement module (`app/agents/mcp_tools.py`, ~200–300 lines, cribbing the conversion shape from adapters under MIT) covers all of it — and kills the known prefix/sanitization mismatch caveat since we'd control naming end-to-end.

**Decision: drop the adapters.** It unblocks the v2 migration immediately (no waiting on #578, no shipping on a fork), removes a dependency whose session-management half we already bypass, and the conversion half is small and fully specified by our own usage.

## OAuth: the path to deleting most of `WebOAuthClientProvider`

The single highest-value v2 simplification: **delete `initiate_authorization`** (the 116-line hand-copied 401 discovery flow, `auth.py:238-354`, "keep in sync with the SDK on upgrades"). Instead, let the SDK's own `async_auth_flow` run the real 401 sequence (PRM → AS metadata → DCR → authorize) and have it *stop at our boundary*: our `_perform_authorization_code_grant` override already persists PKCE state to Redis and raises `OAuthAuthorizationRequired(url)` instead of blocking on a local callback — that override is the *only* piece of the flow that needs to stay custom. Triggering auth becomes "attempt initialize through the client, catch `OAuthAuthorizationRequired`".

What remains after the rewrite (target shape):
- `_perform_authorization_code_grant` override — persist Redis state, raise (serverless model; v2 still assumes blocking handlers)
- `manual_exchange` — the `/callback` completion path
- `_initialize` static-credential injection + `ensure_valid_token`
- `RedisTokenStorage` — survives as-is (same 4-method Protocol; `expires_at` + Google refresh-token carry-over still needed)
- Quirk overrides **only where v2 didn't fix them upstream** — retest each: Notion Basic-auth `client_id` strip, HTTP-201 tolerance, TikTok `none`-only DCR, Supabase `client_secret_post`, Google offline access (v2's SEP-2207 auto-`offline_access` may cover it)

Expected outcome: `auth.py` shrinks from ~478 lines to roughly 150–200, with zero copied SDK flow code left to keep in sync.

## Recommended sequencing

1. **Now:** pin `mcp>=1.26,<2` on main (protects against accidental `uv lock --upgrade` breakage until the migration lands).
2. **Spike branch:** `uv add "mcp>=2,<3"`, **remove** `langchain-mcp-adapters`, write `app/agents/mcp_tools.py` (tool conversion) against v2's `Client`, port `initialize.py`/server-side, and answer the verify-items (lifecycle scaffolding, extension hook for MCP Apps, teardown semantics).
3. **Then:** OAuth rewrite per the target shape above; land as a PR series: deps + adapters removal + tool conversion → server-side port → OAuth rewrite → toolset simplification.

## Local test plan

No infra changes needed; everything runs against the existing dev stack.

```sh
git checkout -b spike/mcp-sdk-v2
cd backend

# mcp v2 + the community adapters port as a git dep
uv add "mcp>=2.0.0,<3"
uv add "langchain-mcp-adapters @ git+https://github.com/chrfsa/langchain-mcp-adapters@feat/mcp-v2"
# httpx2 comes in transitively; httpx stays for langfuse etc.
```

Then, in order:

1. **Boot**: `make dev-stack`, run the backend on a spare port (`uv run uvicorn app.main:app --port 8100`) so the regular dev server is untouched. First failures will be `initialize.py` (private attrs gone) and `mcp.server.fastmcp` imports — comment out the patch application in `main.py:65` and port `router.py`/`main.py` to `MCPServer` to get to boot.
2. **API-key server**: connect any bearer-token MCP server, `list_tools`, run an agent turn. Exercises `connectivity`, `factory`, `toolset` end-to-end.
3. **OAuth server**: connect Notion or Google Sheets — this stress-tests the `auth.py` rewrite surface (expect this to be where the spike spends its time; it's fine to stub `initiate_authorization` minimally just to measure the gap).
4. **Lifecycle**: port `scripts/repro_mcp_session_death.py` to v2; kill the server mid-session. Answers: same-task teardown constraint gone? dead-transport errors typed per-request? → decides `_SessionSupervisor`/`ReconnectingSession` fate.
5. **MCP Apps**: port `scripts/probe_metabase_mcp.py`; check whether v2 offers a supported way to advertise `io.modelcontextprotocol/ui` (extension APIs) and whether output-schema validation can be relaxed.
6. **Latency**: rerun `scripts/diagnose_mcp_timing.py` methodology against the Google Sheets Cloud Run server through the v2 client — confirm the 15s `tools/list` wedge is gone or characterize when it still occurs.

## Sources

- [MCP Python SDK migration guide (v1 → v2)](https://py.sdk.modelcontextprotocol.io/migration/)
- [What's new in v2](https://py.sdk.modelcontextprotocol.io/v2/whats-new/)
- [v2.0.0 release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)
- [v2 client docs](https://py.sdk.modelcontextprotocol.io/v2/client/) · [transports](https://py.sdk.modelcontextprotocol.io/v2/client/transports/) · [OAuth for clients](https://py.sdk.modelcontextprotocol.io/v2/client/oauth-clients/)
- [langchain-mcp-adapters issue #578 — v2 support](https://github.com/langchain-ai/langchain-mcp-adapters/issues/578)
- [chrfsa/langchain-mcp-adapters `feat/mcp-v2`](https://github.com/chrfsa/langchain-mcp-adapters/tree/feat/mcp-v2) (community migration, 2026-08-04)
- [SDK beta announcement for the 2026-07-28 spec](https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/)
- [pydantic: MCP Python SDK v2 beta](https://pydantic.dev/articles/mcp-python-sdk-v2-beta)
- v2 `streamable_http.py` source at tag v2.0.0 (GET stream started on `initialized`, gated on `session_id`, with auto-reconnect)
