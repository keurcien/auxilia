# auxilia backend — software design review

*Reviewed 2026-08-27, against the working tree on `main` (post PR #294). Scope: `backend/` only — architecture, performance, code smells, design patterns, maintainability, contributor experience. Security and UI/UX explicitly out of scope. Based on reading the code, not the docs (which are stale in several places — see §8.1).*

*Method: full reads of the agent runtime (`runtime.py`, `toolset.py`, `stream.py`, `structured_output.py`, `main.py`) plus six parallel deep-review passes over the agent domain layer, the durable-run runtime + triggers, the MCP subsystem, the app foundations (base classes, auth, model_providers), threads/Slack/sandbox, and the test suite/DX. All claims carry `file:line` references; severities are high / medium / low.*

---

## 0. Executive summary

**Your instinct that "it's become very complex" is half right — and the half that's right is fixable without an architecture change.**

The macro-architecture is sound. The layered modular monolith (router → service → repository → model, one module per domain concept) is the right shape for this project and for open-source contribution, and it is *actually followed* about 90% of the time — which is rare. The durable-run runtime, widely suspected of being over-engineered, turns out to be **right-sized**: every moving part maps to a requirement no off-the-shelf queue provides, and the Postgres half already *is* the "simpler SKIP LOCKED design" a replacement would propose. Verdict there: **keep, harden**.

The complexity you feel comes from four specific sources of *accidental* complexity, none of which require DDD, a rewrite, or a framework change:

1. **One fat read path used for everything.** `AgentService.get()` hydrates permissions, tags, owners, sandboxes, and subagent links (~5–6 queries) for every caller — including the run pathway, which resolves the same agent graph **three times per user message** (readiness poll, run-create preflight, worker build) at ~45–60 DB round-trips for an agent with two subagents. This is the single biggest simplicity *and* performance win available.
2. **The dual-path runtime.** `build_runnable` branches between `create_agent` and `create_deep_agent`, which silently gives sandbox agents a different middleware stack (summarization, todo tools, prompt caching) and a different system-prompt shape than plain agents. The fix is to unify — but on `create_agent`, not `create_deep_agent` (§2.3).
3. **Duplication with divergent quality.** The same logic implemented twice with different error policies: readiness probing (sequential + fail-loud) vs run preflight (concurrent + fail-open); auth-type dispatch in `connectivity.py` vs `factory.py` (one raises, one silently connects unauthenticated); six copies of the permission tuple check; three copies of Slack identity resolution.
4. **Contract drift between docs and code.** CLAUDE.md documents files that no longer exist (`hitl.py`, `mcp/utils.py`), a permission model the code doesn't implement, and exception names/status codes that don't match. For an open-source project, the contributor guide describing rules the flagship modules don't follow is the most expensive kind of debt.

And one meta-finding that outranks everything below: **there is no backend CI.** A 667-test, 4.4-second, zero-infrastructure suite exists and nothing runs it on PRs (`.github/workflows/` has frontend CI, docker publish, and release-please only). Fixing that is an afternoon and it protects every other fix in this document.

---

## 1. Direct answers to your questions

### 1.1 Should we move to DDD?

**No.** You already have the parts of DDD that pay for themselves: bounded module boundaries per domain concept, a service layer that owns business logic, the repository pattern, domain exceptions translated at one edge. What full DDD would add — aggregates with invariant-enforcing roots, domain events, value objects everywhere, application vs domain service split, anti-corruption layers — is machinery for taming *domain* complexity (complicated business rules, many bounded contexts, large teams). auxilia's complexity is not domain complexity; it's **integration complexity** (LangGraph, MCP transports, OAuth, Redis lifecycles) plus the accidental complexity in §0. DDD ceremony would not touch either; it would add a vocabulary barrier for contributors and roughly double the file count per feature.

What *is* worth borrowing from DDD, cheaply:

- **Aggregate-shaped reads**: treat "agent config for a run" as one consciously-designed projection (`get_run_spec`, §2.2) instead of reusing the API DTO everywhere.
- **One authorization chokepoint** per module instead of scattered predicates (§4.4).
- **Making the module dependency graph one-directional** (agents ↔ sandbox currently cycle, §6.5).

Reference points: [Polar](https://github.com/polarsource/polar) (FastAPI, similar scale, open-source) uses essentially your architecture — session dependency + service objects + per-module layout — and has scaled contributions fine without DDD. The [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) is *simpler* than you (CRUD in route bodies) and would be a regression at your size. You are in the right middle.

### 1.2 Is the agent resolution pathway simple, fast and clear?

**Clear at the top, neither simple nor fast underneath.** The two-phase design is genuinely good and should be kept: `Toolset.prepare()` (all DB, request scope) / `Toolset.open()` (all network, stream scope) is a clean lifecycle boundary with its ordering invariant documented (`toolset.py:147–159`). The problem is what feeds it.

Traced end-to-end, one user "send" to an agent with N subagents and S MCP servers:

| Step | What happens | Cost |
|---|---|---|
| Frontend polls `GET /agents/{id}/is-ready` | `describe_readiness` → `collect_run_bindings` → full `AgentService.get()` per agent **(1+N) × ~5 queries** (`core/service.py:398–414`), then **sequential** `is_authorized` probes per server (`core/service.py:438–441`), each ≥4 Redis GETs + double Fernet decrypt + possible IdP refresh POST | ~(1+N)×5 queries + S sequential probes, per poll |
| `POST /runs` preflight | `ensure_mcp_authorized` → **`collect_run_bindings` again** (`runs/service.py:158–159`, including its own inline raw `MCPServerDB` query) → probes again (concurrent this time) | same again |
| Worker `Agent.build` | `ResolvedAgent.resolve` per agent, **sequentially** for subagents (`runtime.py:368–371`): full `AgentService.get` + `Toolset.prepare` (per-server `MCPClientConfigFactory.build` awaited sequentially, `toolset.py:424–426`) + sandbox row re-fetch (`runtime.py:238` — refetching a row the readiness path already joined) | ~8 + 7N queries |
| Stream start | `Toolset.open` — concurrent session opens (good) + live `list_tools` per server on **every** turn | S network handshakes per turn |

So: **the same agent graph is fully resolved three times per send**, always through the most expensive read in the module, and the readiness copy is the fragile one (sequential, no exception handling — one probe raising 500s the polled endpoint, vs the preflight's fail-open gather at `runs/service.py:179–181`). Root cause: there is exactly one read path (`get` → `list_with_permissions` → `_assemble`) and it hydrates owner names, tag names, permission resolution and sandbox display fields for internal callers that need only `instructions + bindings + subagent ids`.

Note `asyncio.gather` is **not** the fix for the sequential subagent resolves — they share one `AsyncSession`, which is not concurrency-safe. The fix is batching (§2.2).

Also on this path: `runtime.py:224` has the LangGraph runtime calling `AgentService(db).get(...)` — the runtime depends on the HTTP-facing service and its `AgentResponse` DTO. The run path should depend on a narrow spec/repository, not on API response assembly.

### 1.3 What about the agent runtime?

`runtime.py` (643 lines) is dense but honest: the middleware ordering constraints, the anyio cancel-scope task-hosting in `_open_sessions`, the `return_exceptions=True` rationale in `_setup` — the hard-won invariants are all written down next to the code, which is the main reason this file is maintainable at all. The `ReconnectingSession`/`_SessionSupervisor` machinery in `toolset.py` is justified complexity (the MCP SDK's transport really does die mid-run and there is no upstream fix — SDK GET-SSE deadlock is still open).

The real runtime problems, ranked:

1. **The dual construction path** (§1.4 / §2.3) — the largest removable complexity in the file.
2. **`ResolvedAgent.compile` duplicates the parent middleware stack** with subtly different members (`runtime.py:283–294` vs `build_parent_middleware`), and carries two *documented but unresolved* feature gaps: subagent HITL approval gates are **silently dropped** (`runtime.py:256–259`) and subagent sandboxes never persist (`runtime.py:275–276`). These are honest comments about real product gaps — they should also exist as tracked issues, not only as comments, because a contributor adding "require approval" to a subagent tool gets no error and no effect.
3. **Thin test coverage exactly here**: `test_runtime.py` has 6 tests asserting middleware lists by `isinstance`; `Agent.build`/`stream`, the recursion fallback, and teardown containment are untested. A refactor of this file is currently a leap of faith (§7.2).
4. Minor: `_dicts_to_lc_messages` (`runtime.py:616–643`) hand-rolls what `langchain_core.messages.convert_to_messages` already does; `get_regeneration_checkpoint_id` (`runtime.py:68–80`) walks the full checkpoint history (O(turns) full-state loads) per regeneration.

`stream.py` is in good shape — small, contract-coupled, well tested. The one structural cost: the worker publishes SSE *strings* and the Slack consumer re-parses them with a hand-rolled parser (`stream.py:231–256`). One producer / two consumers is the right topology; the envelope should be a typed event (JSON), SSE-encoded only at the HTTP edge, so Slack delivery doesn't depend on string parsing of your own output.

### 1.4 Should we drop `create_agent` in favor of `create_deep_agent`?

**No — do the opposite: standardize on `create_agent` and compose deepagents' middleware explicitly.**

Verified against the installed `deepagents` 0.5.6: `create_deep_agent` is `create_agent` plus a **fixed** middleware bundle — `TodoListMiddleware`, `FilesystemMiddleware`, `SubAgentMiddleware`, `SummarizationMiddleware`, `PatchToolCallsMiddleware`, and an *unconditional* `AnthropicPromptCachingMiddleware` — and `FilesystemMiddleware`/`SubAgentMiddleware` are **non-excludable** (`deepagents/graph.py:174–197`: excluding them raises `ValueError`).

Consequences of unifying on `create_deep_agent`:
- Every simple chat agent grows todo-list and filesystem tools plus deepagents' harness prompt — prompt bloat and tool confusion for agents that need neither, and a behavior change for every existing thread.
- You'd be adopting summarization and prompt-caching middleware globally as a side effect of a code-simplification, not as a decision.

Consequences of the *current* split (worse than either unification):
- Sandbox agents **already** silently get summarization + prompt caching + todos and plain agents don't — a per-agent behavioral fork that nobody chose per-agent.
- Two system-prompt shapes (`str` vs `SystemMessage`, `runtime.py:402–408` — the comment admits it exists only "to avoid a prompt-shape change").
- The `PatchToolCallsMiddleware` strip-hack (`runtime.py:126–128`) because `create_deep_agent` injects its own and langchain asserts on duplicates.
- Middleware you add to `build_parent_middleware` behaves differently depending on whether the agent happens to have a sandbox bound.

**Proposal:** one construction path through `create_agent`, with an explicit, single middleware assembly:

```python
middleware = [
    PatchToolCallsMiddleware(),
    ModelRetryMiddleware(),
    ToolCallLimitMiddleware(...),
    RepairInvalidToolCallsMiddleware(),
    HumanInTheLoopMiddleware(...),
    CurrentDateMiddleware(created_at),
]
if sandbox:
    middleware.append(FilesystemMiddleware(backend=sandbox_backend))   # from deepagents
    tools += create_sandbox_tools(...)
if subagents:
    middleware.append(SubAgentMiddleware(backend=..., subagents=compiled))
if output_schema:
    middleware.append(DeferredStructuredOutputMiddleware(format_mode))
middleware.append(ToolErrorMiddleware())
return create_agent(model=model, tools=tools, system_prompt=..., middleware=middleware, ...)
```

deepagents stays a dependency — you keep using its middleware (`FilesystemMiddleware`, `SubAgentMiddleware`, `PatchToolCallsMiddleware`) — you just stop using its opinionated assembler. This deletes the dual branch, the strip-hack, the dual prompt shape, and makes the middleware stack *one diffable list*. If you later decide you want summarization or the todo harness, you add that line deliberately, for all agents.

Caveats to verify during the change (worth a short spike): that `FilesystemMiddleware` + your `LazySandboxBackend` behave identically outside `create_deep_agent` (deepagents' harness prompt sections around file tools would no longer be injected — you may want to append the relevant prompt fragment yourself), and that existing sandbox threads tolerate the prompt change (you already freeze prompts per thread from `thread.created_at`, which helps). Also note the planned deepagents 0.7 upgrade (framework-upgrade-assessment.md) — do this unification *first*; it shrinks the upgrade surface to the three middleware classes you actually import.

---

## 2. Architecture findings

### 2.1 The layered contract: mostly real, with named violations

The router→service→repository→model discipline genuinely holds across `users/`, `tokens/`, `invites/`, `model_providers/`, `mcp/servers/`, `tags/`, `teams/`. Violations, so they can be fixed rather than normalized:

| Sev | Where | What |
|---|---|---|
| high | `core/service.py:433–436`, `runs/service.py:158–159` | Raw `select(MCPServerDB)` in services — another module's table, queried inline, twice. Fix: `MCPServerRepository.list_by_ids`. |
| med | `auth/service.py:35,46,52,125,134,144` | `AuthService` uses **zero repositories** — six raw queries. The flagship auth module ignoring the documented convention means newcomers can't tell which pattern is the template. |
| med | `subagents/service.py:34–38`, `invites/service.py:64–66, 93–95` | More raw cross-module selects; `UserRepository.list_by_ids` already exists and isn't used. |
| med | `agents/router.py:176–189, 309–316` | Authorization predicates in the router (see §4.4). |
| med | `threads/router.py:41–93, 117–183` | Checkpoint access, domain filtering, and projection in the router; both endpoints return untyped `dict` with no `*Response` schema. |
| med | `invites/router.py:28,39` | Router calls `service._to_response(...)` — a private method as a cross-layer API. |
| low | `mcp_servers/service.py:51–60,128–131`, `sandboxes/service.py:44–47`, `threads/service.py:118–126` | `db.add`/`flush`/`refresh` scattered in services; repository no longer the single write surface. |
| low | `runtime.py:238` | Runtime imports `SandboxRepository` directly; third distinct cross-module composition style (service / repo-in-init / repo-inline). Pick one and document it. |

### 2.2 The fix for §1.2: a narrow run-spec read

Introduce `AgentRepository.get_run_spec(agent_id) -> RunSpec` (or a small module function) returning, in ≤3 flat queries: the agent row (+ subagent agent rows via one `IN` query), all `AgentMCPServerDB` bindings for parent+subagents (one `IN` query — mirror `sandboxes/repository.py:20`'s `list_for_agents`, which already exists), and sandbox bindings. Then:

- `ResolvedAgent.resolve` consumes `RunSpec` instead of `AgentService.get` — decoupling the runtime from `AgentResponse` (§1.3).
- `collect_run_bindings` becomes a projection of `RunSpec` — killing the (1+N)×5 N+1 (`core/service.py:398–414`).
- `describe_readiness` and `ensure_mcp_authorized` share one `probe_authorization(servers, user_id)` helper in `connectivity.py` — concurrent, fail-open, **cached**: memoize per `(user, server)` in Redis with a ~30s TTL so the frontend's `is-connected`/`is-ready` polling loops stop re-running Fernet decrypts and, worse, IdP refresh attempts every poll (`connectivity.py`, finding 2.2 in §3).

Estimated effect: run-launch DB round-trips drop from ~8+7N to ~4–5 flat; readiness polls become Redis-only; three divergent implementations become one.

### 2.3 Other architecture-level findings

- **high — Background loops are fire-and-forget with no supervision** (`main.py:76–91`): a crashed `RunDispatcher` logs one ERROR and the instance keeps serving 200s while no run ever executes again. Wrap each loop in a supervisor (`while True: try/except + backoff`) and/or expose task liveness on a health endpoint Cloud Run can act on.
- **med — `ExceptionGroup` handler swallows domain exceptions into 500s** (`main.py:113–142`): a `NotFoundError` raised inside a TaskGroup arrives wrapped, misses its dedicated handler, and re-raises as 500. `root_cause()` (`exceptions.py:1–7`) exists precisely for this — use it in the group branch and re-dispatch. While there: replace the six copy-paste handlers (`main.py:145–188`) with one `STATUS: dict[type, int]` mapping.
- **med — root mount of the FastMCP app** (`main.py:229`): every unmatched route falls into the mounted sub-app, which owns 404 semantics and bypasses your exception handlers — and the mounted server currently ships **hardcoded demo tools returning lorem ipsum** (`mcp/router.py:40–48`). Gate or delete the demo tools; mount under a prefix if the protocol allows.
- **med — agents ↔ sandbox module cycle** (`sandbox/service.py:103,121` lazily importing `app.agents.sandboxes.repository`; `sandbox/provider.py:78–81` lazily importing its own subpackages). Lazy imports as cycle-breakers are traps — moving one to the top of the file breaks the app at import time only. Make the dependency one-directional (agents orchestrates detach-and-delete, calling down into sandbox), and move the provider registry to a leaf module.
- **low — `client/` vs `servers/` inversion in MCP**: `client/connectivity.py` imports `servers/`' repository, models, schemas, and encryption; `ConnectionTestResult` lives in `servers/schemas.py` but is constructed only in `client/`. `connectivity` is really a domain module; name and place it as one.

### 2.4 The MCP OAuth trigger: right mechanism, wrong catch site

*(Added 2026-08-27 after a follow-up question; verified against python-sdk v2.0.0 source and the TypeScript SDK docs.)*

Today, "user needs to authorize this MCP server" is signaled by `OAuthAuthorizationRequired(auth_url)` raised from an overridden SDK-private (`_perform_authorization_code_grant`, `client/auth.py:439`) and caught **app-globally** in `main.py:113–142`, with `ExceptionGroup.subgroup()` unwrapping because the implicit 401 path can fire deep inside anyio task groups on any endpoint that touches MCP.

**The exception mechanism itself is sound** — the TypeScript SDK, the reference implementation for this problem, does the same thing: `connect()` throws `UnauthorizedError` when authorization is needed, and the two-request web flow (persisted PKCE verifier + discovery state, public `transport.finishAuth(params)`) is first-class on its `OAuthClientProvider` interface (`saveCodeVerifier`/`codeVerifier`, `saveDiscoveryState`/`discoveryState`, `state()`). Our Redis-persisted verifier/client-info/metadata + `manual_exchange` is the same architecture — independently reinvented, and validated by theirs. The two differences that make ours feel unclean:

1. **TS catches at the connection call site, not globally.** The exception is a bare sentinel; the auth URL travels through a provider callback (`redirectToAuthorization(url)`), not inside the exception.
2. **TS exposes the flow as a public contract**; ours reimplements ~120 lines of SDK-inlined orchestration (`initiate_authorization`, `client/auth.py:238–354`) with a keep-in-sync-on-upgrade warning.

**Python SDK v2 does not fix this.** v2.0.0 (stable, 2026-07-28) still inlines the entire client OAuth flow inside the httpx `async_auth_flow` generator, driven by `redirect_handler`/`callback_handler` coroutines that must complete within one request lifecycle — the interactive in-process model. Discovery/DCR/authorize-URL construction remain private; there is no public "give me the auth URL" or "finish with this code" API. (Moot for now anyway: `langchain-mcp-adapters` doesn't support `mcp>=2` — issue #578 open, no linked PR.) The TS provider seam is a legitimate upstream feature request for the Python SDK; `WebOAuthClientProvider` is effectively a working prototype of it.

**Recommended design** (slots into Phase 3):

1. **Make "begin OAuth" always explicit, never a side effect.** Only endpoints whose job involves connecting (`test-connection`, `list-tools`, sync, run preflight) may return an auth URL — via normal control flow and a typed discriminated-union `*Response` (`{"status": "auth_required", "auth_url": ...}`), not via an exception deciding the response shape.
2. **Catch the implicit 401 at the MCP seam, inside the task-group scope.** Most consumers already do this — `runs/worker.py:67`, `runs/service.py:189`, `triggers/service.py:248`, `connectivity.py:258,272` all handle the exception locally (mid-run 401s already become `MCP_REAUTH_ERROR`, the right pattern). Close the remaining gap in `connectivity._open_session` / the `Toolset.open` gather (unwrap with `root_cause()`), so no `OAuthAuthorizationRequired` can escape a boundary.
3. **Then delete the global handler and the `ExceptionGroup` registration in `main.py` entirely** — which also fixes the §2.3 bug where that handler swallows TaskGroup-wrapped domain exceptions into 500s.
4. Optional polish: have the provider *store/return* the pending auth URL and raise a data-less sentinel (the TS shape); keep `manual_exchange` as-is, optionally renamed `finish_auth(params)` and hardened with the TS SDK's callback-`iss`-vs-discovery-state check (mix-up attack guard, cheap to add).

Net effect: OAuth triggers only where a reader expects it, the `ExceptionGroup` unwrap hack disappears, `main.py` loses its weirdest handler, and the SDK-drift surface shrinks to `initiate_authorization` + `manual_exchange`.

---

## 3. Performance findings (ranked)

1. **high — Argon2 verification runs synchronously on the event loop on every PAT request** (`auth/tokens/repository.py:33`, `auth/utils.py:12–22`, called from `auth/dependencies.py:41–45`). Argon2id is deliberately slow and memory-hard; every Bearer-PAT request blocks the loop for tens of ms — stalling all in-flight SSE streams — and does so *per candidate* in a prefix scan. Two-part fix: (a) PATs are 32 bytes of `secrets.token_urlsafe` entropy — hash with SHA-256 and look up by indexed digest equality (what GitHub/GitLab do); keep Argon2 for passwords only. (b) Until then, `asyncio.to_thread` around every verify/hash. Enable ruff's `ASYNC` rule group, which flags this class of bug and is currently off (`pyproject.toml:63`).
2. **high — the triple agent-graph resolution per send** (§1.2/§2.2).
3. **high — `TokenStorageFactory()` builds a new, never-closed Redis connection pool at eight call sites** (`storage.py:176–183`; call sites in `connectivity.py`, `servers/service.py`, `factory.py`) — every readiness probe, is-connected poll, agent build, and OAuth callback allocates a fresh `ConnectionPool`; `aclose` is never called anywhere. The lifespan-managed `app/redis_client.get_redis()` exists and is ignored. Fix: inject the shared client; make the factory a dependency/singleton; delete the `localhost:6379` default constructor args (`storage.py:37–47`) which are dead code and a deployment trap.
4. **med — one awaited `XADD` per SSE chunk, serial with the agent stream** (`runs/worker.py:192–201`): every token pays a Redis RTT inline; a 3,000-chunk run on managed Redis adds seconds of wall clock. Fix: small bounded buffer flushed via pipeline every N chunks / T ms (tail-loss already accepted by the `MAXLEN` approximate trim).
5. **med — the agents list query ships every agent's multi-KB `instructions` blob × join fan-out** (`core/repository.py:56–77`) only for the service to drop them from `AgentListResponse` (`schemas.py:185–189`). Use explicit columns / `load_only`, or fetch bindings in a separate `IN` query.
6. **med — mutation endpoints re-hydrate everything, plus a redundant `get_or_404`** (`core/service.py:250–276`): a one-column PATCH costs ~12 round-trips (full `get` for the permission string, `get_or_404` refetching the row `get` already held, `update`, full `get` again). Per-row loops compound it: five copies of select-then-delete-each for link tables (`core/repository.py:92–97,139–144`; `mcp_servers/repository.py:27–34,47–56`; `subagents/repository.py:77–89`; `sandboxes/repository.py:45–52` — `delete_permanently` chains four of them, ~35 round-trips), and `set_permissions` refreshes N rows to read timestamps its response schema doesn't include (`core/repository.py:106–127`). Fix: bulk `DELETE ... WHERE`, drop the refresh loop, add a `get_row_with_permission` single-query read.
7. **med — trigger claim transaction can hold row locks across a CDN fetch** (`triggers/service.py:296–337` calling `model_service.is_available` inside the claim txn on a cold catalog cache). `RunService.create` already pre-warms the whitelist for exactly this reason (`runs/service.py:79–82`); the scanner should too.
8. **med — `get_subagent_state` deserializes every checkpoint in the thread** (`threads/router.py:158–168`) hunting for a seed-message match; `read_thread` fetches the thread twice, runs 4+ sequential pre-checkpoint queries, and returns the full history **twice** in two encodings (`router.py:77,87`). Fix: persist the `tool_call_id → checkpoint_ns` mapping at run time so subagent state becomes one `aget`; pick one wire format for history.
9. **low —** sequential `MCPClientConfigFactory.build` per server (`toolset.py:424–426`); `is_authorized`'s double token read + double decrypt (`auth.py:92–95` then `:151–154`); `list_connections` N sequential Redis GETs (`servers/service.py:224–227` — use `MGET`); OpenSandbox 100 ms HTTP polling (~600 requests/min-long command, `opensandbox/backend.py:60–77`) and IO-in-a-property `OpenSandbox.id` (`:36–38`); `GatewayTransport`'s never-closed `httpx.Client` per run (`cloudrun/transport.py:70–72`); blocking `Path.read_text`+YAML on the async path in `remote_catalog.bundled()`; `get_db` issuing a COMMIT round-trip on pure reads.

---

## 4. Code smells & duplication catalog

### 4.1 Same logic, N implementations

| What | Copies | Divergence |
|---|---|---|
| Readiness / auth probing | `core/service.py:416–447` vs `runs/service.py:120–196` | sequential+fail-loud vs concurrent+fail-open; the fragile one is on the polled endpoint; `describe_readiness` also returns `"status": "disconnected"` as a constant even when everything is connected (`core/service.py:443–447`) |
| Auth-type → transport dispatch | `connectivity.py:180–199` vs `client/factory.py:16–41` | factory raises on unknown type; `connect_to_server` **silently connects unauthenticated**; both share the `Bearer None` bug (a missing API-key row formats `None` into the header, `connectivity.py:188–191`, `factory.py:26–27`) |
| Per-server OAuth quirks | `auth.py:102–108, 307–314, 422–428` + `servers/service.py:276–279` | the Supabase quirk exists twice with two different match keys (issuer vs URL) in two layers; Gmail scopes hardcoded with a TODO. Fix: one `OAUTH_QUIRKS` table in `client/auth.py` |
| Permission gate `in ("owner", "admin", ...)` | 6 sites (`agents/router.py:176–189,309–316`; `core/service.py:261,292,341,367`) | hand-typed tuples, no ordering — see §4.4 |
| Whole-set replace (diff + upsert + delete) | `mcp_servers/service.py:115–143`, `sandboxes/service.py:20–56`, `subagents/service.py:110–133` | three hand-rolled diffs, different flush timing; subagents re-runs 4 validation queries **per item** |
| Slack identity resolution | `utils.py:84–90`, inline in `handlers.py:200–207`, inline in `chat.py:180–185` | already drifting on `user_info` needs; `_extract_interaction_context` also duplicated verbatim (`handlers.py:390–403` / `chat.py:167–175`) |
| Background-loop skeleton | `reaper.py:96–102`, `worker.py:276–279`, `scanner.py:44–47` | a 15-line `PeriodicLoop(interval, tick)` base deletes ~60 lines and gives new loops supervision for free (§2.3) |
| `ROOT_ENV` derivation | 12 settings files, each counting `.parent`s to find `.env` | depth silently depends on file location; `extra="ignore"` masks a wrong path. Export `ROOT_ENV` + a shared `SettingsConfigDict` from `app/settings.py`. Several files also annotate `model_config` as pydantic's `ConfigDict` instead of `SettingsConfigDict`, so config-key typos are invisible to type checkers |
| email-availability check | `users/service.py:32–34` (via repo), `auth/service.py:45–48` (raw), `invites/service.py:64–66` (raw) | two of three bypass the layer the docs mandate |
| OAuth-preflight + commit stanza | `runs/router.py:109–126, 151–168, 200–215` | copy-pasted thrice; extract a FastAPI dependency |
| `mock_db` test fixture | root conftest + 9 module conftests | each drifting slightly |

### 4.2 Stringly-typed state where it hurts most

The two most concurrency-sensitive areas — run delivery and Slack HITL — are exactly where inter-layer contracts are strings the type checker can't see:

- `MCP_REAUTH_ERROR` matched by **exact string equality** on `RunDB.error` (`runs/state.py:24–32`) — any rewording silently breaks the Slack reconnect affordance. Add an `error_code` column.
- Slack HITL approval state recovered by scanning message blocks for `:white_check_mark:` emoji (`slack/handlers.py:84–98`) — clever stateless design, honestly documented, but an innocent copy tweak makes every batch look undecided and the agent never resumes. Put the decision in a machine-readable `block_id`; keep emoji as presentation.
- `delivery["channel"] == "slack"`, `{"type": "text"}` event dicts, `status == RunStatus.x.value` comparisons (`consumer.py:42,91–95`), `state == "result"` part states, tool-call rejection detected via `"rejected" in error_text.lower()` (`threads/serialization.py:77`). TypedDict/enum envelopes are cheap and make the dispatch checkable.
- `RunDB.multitask_strategy: str` vs `Literal` in the schema (`runs/models.py:68–70` / `schemas.py:20`); `RunDB.trigger` (a langgraph config tag) colliding with the Trigger entity name.

### 4.3 Dead / misleading code

- **Three dead sandbox settings modules** (`sandbox/settings.py`, `opensandbox/settings.py`, `cloudrun/settings.py`) consumed by nothing in `app/` — kept alive only by their own tests, with docstrings claiming call sites that no longer exist. Delete all three + the test. Dead *config* is worse than dead logic: a contributor will set `SANDBOX_PROVIDER=` and lose an afternoon.
- ETag plumbing in `remote_catalog.py` stores etags nothing ever reads (no `If-None-Match`). Implement the conditional GET (sync becomes ~free) or delete it.
- `ModelProviderType.ollama` (`model_providers/models.py:14`) — unreachable enum member.
- `AgentService.create` (`core/service.py:161–162`) — pass-through no router uses.
- `SubagentResponse.color` declared but never populated (`schemas.py:167` vs `subagents/service.py:20–26`).
- The half-finished `encrypt_api_key → encrypt_value` rename: new names imported and aliased **back to the old names** (`mcp/servers/repository.py:8–11`, `connectivity.py:31`).
- CORS `allow_origins=["*"]` + `allow_credentials=True` (`main.py:191–197`) — a combination browsers reject; all browser traffic rides the Next proxy anyway. Dead-but-misleading.
- `UserCreate`/`UserPatch` expose `password_hash` as an API input field (`users/schemas.py:12,19`) — a storage column leaking through the DTO boundary; accept `password`, hash in the service.

### 4.4 Permissions: right algorithm, wrong type

`_resolve_permission` (`core/service.py:61–78`) is well done — resolved from maps built in one joined query, no N+1. But it returns a bare `str`, so "editor or better" is enumerated as hand-typed tuples at six sites across two layers, and mutation endpoints have drifted: PATCH gates in the service, `PUT /teams` gates in the router, binding/permission endpoints gate **nothing beyond login** (`agents/router.py:157–173, 213–263`). One ordered `EffectivePermission(str, Enum)` + `AgentService.require_permission(agent_id, user, at_least=...)` collapses all of it and ends the drift. (Also: CLAUDE.md documents levels `user/editor/admin`; code has `member/editor/admin` plus team-derived membership CLAUDE.md doesn't mention.)

### 4.5 Schema/DTO sprawl: verdict — mostly earning its keep

20 DTOs in `agents/schemas.py`. The core split is good API design (`AgentListResponse` vs `AgentResponse`, `AgentConfig` as an atomic save document, `*Patch` with `exclude_unset`). Trim the edges: two field-for-field identical twin pairs (`AgentPermissionResponse`≡`Create`, `AgentTeamsSet`≡`Response`), the color validator copy-pasted three times (`schemas.py:24–29,40–45,83–88` — one `Annotated` alias), and `AgentResponse(AgentListResponse)` re-typing an inherited field. `BaseService`/`BaseRepository` also earn their keep (78 call sites, subclasses extend rather than bypass) — two cheap upgrades: link the TypeVars and let the base construct the repository from a class attribute, deleting a boilerplate line per subclass. Nobody type-checks the generics though: **there is no mypy/pyright config at all** — for a codebase leaning on generics, add one (start non-strict).

---

## 5. Correctness risks found along the way

Not the review's focus, but too important to omit. Durable runs (overall verdict: **keep — right-sized**, ~1,300 lines, no speculative abstraction, and the per-thread mutex as a partial unique index + claim-as-transition + `state.py` as the single transition table are genuinely excellent):

1. **high — heartbeat task dies permanently on a single Redis blip** (`runs/worker.py:204–208`): one transient error kills the loop silently; liveness expires; the reaper finalizes a healthy streaming run as `error`. The cancel watcher got defensive treatment; the heartbeat didn't. Wrap the stamp in try/except.
2. **high — the reaper falsely kills healthy queued runs under backlog** (`repository.py:177–195`, `reaper.py:64–76`): "pending > 600s with no running run on its thread" is also the state of every run waiting for a worker slot; a burst of ~30 trigger firings (each on a fresh thread, `triggers/service.py:335`) guarantees healthy runs get reaped mid-queue. Distinguish "no dispatcher alive" (cluster liveness key) from "dispatchers busy".
3. **med — a Redis restart can mass-reap running runs** (single-sample "key missing = dead"; require two consecutive missing sweeps).
4. **med — Redis event streams leak forever if the run row vanishes mid-run** (thread deleted while streaming → CASCADE → `_expire_ephemera` skipped, `runs/service.py:327–329`). Call it unconditionally; add a safety TTL on first XADD.
5. **high — `delete_thread` purges checkpoints *before* the row delete commits** (`threads/router.py:223–235`), the exact opposite of `purge_checkpoints`' own documented contract (`threads/service.py:162–173`); a failed commit leaves a thread whose history is irrecoverably gone.
6. **high — Slack event tasks are fire-and-forget with no strong reference** (`slack/router.py:43,57–59,78–80` — the documented asyncio GC footgun on your only Slack execution path) and **webhook dedup is per-process on a multi-instance deployment** (`router.py:30–55`; a Redis `SET NX EX` is a 3-line fix). Plus `payload.event` is Optional but dereferenced unconditionally (`router.py:42`) — one malformed callback = poison-retry 500 loop.
7. **med — `_open_session` rewraps caller-body exceptions as `DomainError`** (`connectivity.py:135–145`) — the `yield` sits inside the `try`, so exceptions from the caller's block get laundered into 500s. Narrow the try to the handshake.
8. **med — `MCPServerService.update` leaves stale state on auth-type/URL changes** (`servers/service.py:115–139`): orphaned credential rows, Redis tokens issued for the old resource.
9. **med — `get_current_user_optional` has different auth precedence than `get_current_user`** (`auth/dependencies.py:84–102` vs `54–81`): stale cookie + valid PAT authenticates on required endpoints, is anonymous on optional ones. Implement one shared resolver.
10. Langfuse: client built as a module-level import side effect (`callback.py:24` — a bad URL kills every import of `runtime.py` at startup) and no `flush()` on shutdown (scale-to-zero loses trace tails).

Also worth stating as an invariant (it's correct but undocumented): **reaped runs are never retried** — at-most-once execution is the right call for non-idempotent LLM turns, but a contributor coming from Celery will assume redelivery. One sentence in `runs/SPEC.md`.

---

## 6. Contributor experience

### 6.1 What a new contributor hits, in order

1. **CLAUDE.md describes a repo that no longer exists** in places: `app/agents/hitl.py` (gone), `app/mcp/utils.py` (folded into `connectivity.py` in PR #224), `scripts/` (gitignored — the docs point at ghost files including `diagnose_mcp_timing.py`), exception table says `ValidationError`/`AlreadyExistsError→400` (code: `DomainValidationError`/`409`), permission levels wrong (§4.4), transaction contract describes two regimes when there are three (routers legitimately commit mid-request in `runs/router.py:117,159,205,268` and `triggers/service.py:254,337` — good code, undocumented rule). The `list-tools` endpoint docstring still claims raw-HTTP behavior removed months ago (`servers/router.py:184–186`) — on the known 15-second-wedge footgun, of all places.
2. **No CI, no CONTRIBUTING, no coverage.** `uv sync && uv run pytest` from a cold clone is green in 4.4s with zero external services — genuinely rare and worth protecting — and nothing runs it. *(Correction, 2026-08-28: this was not actually true when written. `MCPServerSettings` requires `SALT` at import time, so a clone with no `.env` failed to even collect; it only looked true because a developer's `.env` supplied it. Fixed under P0-1 by defaulting `SALT` in `tests/conftest.py`, which is what the first CI run on a clean checkout exposed.)* `pyproject.toml` still says `description = "Add your description here"`.
3. **No "add a feature" template pointer.** `users/` is the best module in the codebase (clean layers, escaped LIKE search, deterministic ordering, route-ordering comments) — say so in CONTRIBUTING. `invites/` is almost as good but teaches three bad habits (§2.1) — worth a small cleanup pass precisely because it will be copied.
4. **Adding an MCP auth scheme takes 8 scattered edits** with no exhaustiveness help, one of which fails silently (§4.1). One `resolve_transport_auth(server, user_id, repo)` seam + `match` on the enum cuts it to three.
5. Naming potholes: `model_providers/catalog.py` contains no catalog (the catalog is in `whitelist.py`; rename to `factory.py`), `mcp/client/initialize.py` is SDK monkey-patches (`sdk_patches.py`), `create_or_update` methods that don't update (`subagents/repository.py:58`) or return 201 on update (`router.py:213–227`), `_sync_tools` swallowing all exceptions so a failed explicit sync returns success (`mcp_servers/service.py:61–62` — a recurring foot-gun already in your project memory).

### 6.2 Tests: a two-tier suite

**Tier A (newer code) is model testing**: `tests/agents/runs/` drives the real `RunWorker.run()` over fakeredis + real SQLite, asserting lifecycle invariants (cancel mid-run, exception-group unwrapping, liveness cleanup); stream tests exercise the real wire boundary; test docstrings cite the production incidents that motivated them — the suite is a regression ledger.

**Tier B (older CRUD) is mock-mirrors**: `AsyncMock` sessions with `execute.side_effect = [r1, r2]` hard-coding query count *and order* (any refactor breaks tests with opaque `StopIteration`), and ~70 `assert_awaited_once_with` delegation tautologies in `tests/agents/core/test_service.py` alone. These tests are the main *cost* of the refactors this review proposes — budget for deleting most of them, keeping only orchestration-order tests that encode real invariants.

**Gaps, ranked**: (1) `app/auth/` — **zero tests**, and every router test overrides the auth dependencies, so `require_editor` etc. are never executed by any test; (2) no Postgres lane — `claim_next`'s `SKIP LOCKED` + the partial unique index (the most concurrency-critical SQL in the system) and all 47 migrations are never executed by tests (add a `postgres`-marked lane against `docker-compose.dev.yml`, skipped when absent); (3) `runtime.py`'s `Agent.build/stream`, the reaper loop, the trigger scanner's `claim_and_enqueue`, and `serialization.deserialize_to_ui_messages` are the scariest-to-touch code and the least tested.

Alembic hygiene is genuinely good — 47 revisions, single root, single head, zero merges despite the multi-branch shared-DB workflow — with two foot-guns: hand-typed non-hex revision IDs, and `env.py`'s manual model-import registry (a forgotten import makes autogenerate emit a table *deletion*; add a metadata-completeness test).

---

## 7. What's genuinely good (protect these)

- **The comment culture.** Nearly every non-obvious decision states its *why and its failure mode* inline — the `_open_sessions` cancel-scope hosting, the refresh-token carry-over, the flush-before-set for the partial unique index, the fail-open preflight. This is the codebase's single strongest asset; enforce it in review.
- **`runs/` as a subsystem**: Postgres-as-queue with the per-thread mutex as a partial unique index, `state.py` as a single transition table both Python and the SQL guards derive from, storage split by data lifetime, SPEC.md documenting every deviation. Also the delivery topology: one canonical event log, web and Slack as symmetric consumers, Slack HITL resuming through the same pipeline.
- **`remote_catalog.py`**: five-layer freshness fallback, single-flight locking, all-or-nothing validation — production-grade, documented in execution order, reused by two catalogs.
- **`Toolset.prepare`/`open`** as a lifecycle boundary, and `ReconnectingSession` as a measured response to a real upstream defect.
- **Transaction discipline** (flush-not-commit held everywhere it should be), the exception→handler contract followed ~90% of the time, DB-enforced invariants (partial unique indexes, `for_update` revalidation), the 4.4-second zero-infra test suite, and the linear Alembic history.

---

## 8. Proposal: the simplification plan

Ordered so each phase de-risks the next. Phases 0–2 are the "simplify before adding features" you asked for; estimates assume one person familiar with the code.

### Phase 0 — Guardrails (≈2 days, do first)
1. `backend-ci.yml`: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest -q` on `backend/**` PRs. Add `pytest-cov` reporting (don't gate yet).
2. Enable ruff `ASYNC` (+`SIM`, `RUF`); fix what it finds (it will find §3.1).
3. Fix CLAUDE.md drift (§6.1) and write the third transaction regime down. Delete the dead sandbox settings trio, the demo MCP tools, and the doc references to gitignored `scripts/`.
4. Auth tests: pure-function tests for `auth/utils.py` + one `TestClient` test per role gate without overrides.

### Phase 1 — Hot path & stability (≈1 week)
1. `get_run_spec` + shared `probe_authorization` with 30s Redis memoization (§2.2) — kills the triple resolution, the N+1, and the divergent probe implementations in one move.
2. PAT hashing → SHA-256 indexed lookup; `to_thread` around remaining Argon2 (§3.1).
3. `TokenStorageFactory` on the shared Redis client (§3.3).
4. The four runs-runtime defects (§5.1–5.4) + reaper/scanner tests + a Mermaid state diagram in SPEC.md. (~2 days per the subsystem review.)
5. Slack: task references + Redis dedup + Optional-event guard (§5.6).
6. Thread delete ordering (§5.5).

### Phase 2 — Runtime unification (≈1 week, before the deepagents 0.7 / langchain upgrades)
1. Unify `build_runnable` on `create_agent` + explicit middleware composition (§1.4), behind a short spike verifying `FilesystemMiddleware` parity. Decide *deliberately* whether summarization/prompt-caching stay, for all agents.
2. Share one middleware assembly between parent and `ResolvedAgent.compile`; file tracked issues for subagent HITL and sandbox persistence gaps.
3. Batch subagent resolution (no gather — one session; batch the queries).
4. Behavioral tests for `Agent.build`/`stream` with a scripted fake chat model, so the graph actually runs under test before you refactor it.
5. Replace `_dicts_to_lc_messages` with `convert_to_messages`.

### Phase 3 — Consolidation (ongoing, PR-sized chunks)
1. `EffectivePermission` enum + `require_permission` chokepoint; gate the ungated agent mutation endpoints (§4.4).
2. `resolve_transport_auth` + `OAUTH_QUIRKS` table; fix `Bearer None` and the silent unauthenticated connect (§4.1). In the same area: move the OAuth-required catch from the global handler to the MCP boundary and delete the `ExceptionGroup` handler in `main.py` (§2.4).
3. Bulk deletes, drop redundant refresh/`get_or_404`s, slim the list query (§3.6, §3.5).
4. Typed event envelopes for run delivery + Slack; `error_code` column; machine-readable HITL block ids (§4.2).
5. `PeriodicLoop` base with supervision; exception-handler mapping + `root_cause` in the ExceptionGroup branch (§2.3).
6. Extract thread read logic from the router into a service with `*Response` schemas; stable UI message ids (`serialization.py:212` — derive from LangChain ids instead of `uuid4` per read).
7. `AuthService`/`invites` repository cleanup so the template modules teach the right habits; collapse twin DTOs; the renames (`catalog.py→factory.py`, `initialize.py→sdk_patches.py`); shared `ROOT_ENV`/`SettingsConfigDict`.
8. Postgres test lane for `claim_next` + migrations.
9. Progressively delete Tier-B mock-mirror tests as each module is touched.

### What NOT to do
- **Don't adopt DDD** (§1.1). **Don't replace the runs runtime** with arq/taskiq/Celery — none provide the reattachable event log, cooperative cancel, or HITL semantics; the only coherent replacement is LangGraph Platform, which you've deliberately chosen not to depend on. **Don't unify on `create_deep_agent`** (§1.4). **Don't split into services/packages** — the module boundaries are right; they just need the cycles removed and the docs to match.

---

*Cross-cutting sources for patterns referenced: Polar (polarsource/polar) for FastAPI service-layer conventions at comparable scale; GitHub/GitLab token-storage practice for the PAT hashing fix; LangGraph Server as the design reference the runs runtime deliberately mirrors; deepagents 0.5.6 source (`deepagents/graph.py`) for the `create_deep_agent` middleware analysis.*

---

## 9. Implementation plan (task breakdown)

*Added 2026-08-28. §8 gives the phases and the reasoning; this section is the executable
breakdown — one row per shippable PR-sized task, with the files it touches and its
done-when. Progress is tracked in [`backend-cleanup-todo.md`](./backend-cleanup-todo.md);
this section is the specification, that file is the checklist.*

Task IDs are stable (`P0-1`, `P1-3`, …) so they can be referenced from commits, PR titles
and issues. Ordering inside a phase is the recommended execution order; tasks marked
**⛓ blocks** must land before the tasks they gate.

### Phase 0 — Guardrails

Nothing in this phase changes runtime behaviour. It exists so every later phase has a
safety net, and it is cheap enough to land in one sitting.

| ID | Task | Files | Done when |
|---|---|---|---|
| **P0-1** ⛓ blocks all | Backend CI workflow: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest -q`, coverage report (not gated) on `backend/**` PRs | `.github/workflows/backend-ci.yml` | A PR touching `backend/` runs lint + 667 tests; failures block merge |
| **P0-2** | Enable ruff `ASYNC`, `SIM`, `RUF` rule groups and fix the findings (this is what surfaces §3.1's sync-Argon2-on-the-loop) | `backend/pyproject.toml` + fallout | `ruff check .` clean with the new groups selected |
| **P0-3** | Non-strict type checking: add mypy config + a `mypy app` CI step over the modules that lean on generics (`repository.py`, `service.py`, `schemas.py`) | `backend/pyproject.toml`, `.github/workflows/backend-ci.yml` | `mypy` runs clean at the chosen strictness; errors elsewhere are ignored per-module, not globally |
| **P0-4** | Delete dead code: the three sandbox settings modules + their test, the demo lorem-ipsum MCP tools, `ModelProviderType.ollama`, `AgentService.create`, `SubagentResponse.color`, the `encrypt_value→encrypt_api_key` re-aliasing, CORS `allow_origins=["*"]` (§4.3) | `app/sandbox/settings.py`, `app/sandbox/*/settings.py`, `tests/sandbox/test_settings.py`, `app/mcp/router.py`, `app/model_providers/models.py`, `app/agents/core/service.py`, `app/agents/schemas.py`, `app/mcp/servers/repository.py`, `app/mcp/client/connectivity.py`, `app/main.py` | Tests green; `rg` finds no references to the deleted names |
| **P0-5** | Fix doc drift (§6.1): CLAUDE.md ghost files (`agents/hitl.py`, `mcp/utils.py`, `scripts/`), the exception table (`DomainValidationError`, 409), the permission levels, the **third** transaction regime (routers that legitimately commit mid-request), and the stale `list-tools` docstring. Fill in `pyproject.toml`'s placeholder description | `CLAUDE.md`, `backend/pyproject.toml`, `app/mcp/servers/router.py`, `backend/app/agents/runs/SPEC.md` | Every path named in CLAUDE.md exists; exception table matches `app/exceptions.py` + `main.py` |
| **P0-6** | `CONTRIBUTING.md` for the backend: the layered contract, `users/` as the reference module, the comment culture rule, how to run the suite | `CONTRIBUTING.md` | A cold clone can add a feature module by following it |
| **P0-7** | Auth tests (currently zero, §6.2): pure-function tests for `auth/utils.py`, and one `TestClient` test per role gate **without** dependency overrides so `require_editor`/`require_admin` actually execute | `tests/auth/` | `require_editor`, `require_admin`, `get_current_user`, `get_current_user_optional` each covered |
| **P0-8** | Document the at-most-once invariant (reaped runs are never retried) + a Mermaid state diagram in the runs SPEC | `app/agents/runs/SPEC.md` | Stated explicitly, with the rationale (non-idempotent LLM turns) |

### Phase 1 — Hot path & stability

| ID | Task | Files | Done when |
|---|---|---|---|
| **P1-1** | **PAT lookup → SHA-256 indexed digest** (§3.1a). PATs are 32 bytes of `secrets` entropy, so Argon2 buys nothing; hash with SHA-256, look up by indexed equality, keep Argon2 for passwords. Needs a migration + a verify-then-rehash path for existing tokens (or an accepted one-time invalidation — decide and document) | `app/auth/tokens/{models,repository,service}.py`, `app/auth/utils.py`, `alembic/versions/` | Bearer-PAT auth is one indexed query, no Argon2 on the request path |
| **P1-2** | `asyncio.to_thread` around the remaining Argon2 verify/hash (password signin/signup) (§3.1b) | `app/auth/utils.py`, `app/auth/service.py` | No `PasswordHash` call runs directly on the event loop |
| **P1-3** | `TokenStorageFactory` on the shared lifespan Redis client (§3.3): inject `get_redis()`, delete the eight ad-hoc pools and the `localhost:6379` default constructor args | `app/mcp/client/storage.py`, `app/mcp/client/{connectivity,factory}.py`, `app/mcp/servers/service.py`, `app/redis_client.py` | No `ConnectionPool` is constructed outside `redis_client.py` |
| **P1-4** ⛓ blocks P1-5 | **`AgentRepository.get_run_spec(agent_id) -> RunSpec`** (§2.2): the agent row + subagent rows in one `IN` query, all `AgentMCPServerDB` bindings for parent+subagents in one `IN` query, sandbox bindings in one (mirror `sandboxes/repository.list_for_agents`) | `app/agents/core/repository.py`, `app/agents/schemas.py` (or a new `run_spec.py`) | ≤3 flat queries for an agent graph of any width; covered by a query-count test |
| **P1-5** | Consume `RunSpec` everywhere the graph is resolved: `ResolvedAgent.resolve` (drops the runtime's dependency on `AgentService`/`AgentResponse`), `collect_run_bindings`, the sandbox row re-fetch at `runtime.py:238` | `app/agents/runtime.py`, `app/agents/core/service.py`, `app/agents/runs/service.py` | Run launch drops from ~8+7N round-trips to ~4–5; `runtime.py` no longer imports `AgentService` |
| **P1-6** | One `probe_authorization(servers, user_id)` in `connectivity.py` — concurrent, fail-open, memoized per `(user, server)` in Redis at ~30s TTL — replacing the sequential fail-loud copy in `describe_readiness` and the copy in `ensure_mcp_authorized`. Fix `describe_readiness` returning a constant `"disconnected"` status | `app/mcp/client/connectivity.py`, `app/agents/core/service.py`, `app/agents/runs/service.py` | One implementation; readiness polls are Redis-only; no probe raising can 500 the polled endpoint |
| **P1-7** | Move the two raw `select(MCPServerDB)`s out of services into `MCPServerRepository.list_by_ids` (§2.1, high) | `app/mcp/servers/repository.py`, `app/agents/core/service.py`, `app/agents/runs/service.py` | No `select(MCPServerDB)` outside `app/mcp/servers/` |
| **P1-8** | Runs-runtime defects §5.1–5.4: heartbeat survives a Redis blip; the reaper distinguishes "no dispatcher alive" from "dispatchers busy" (cluster liveness key) before killing queued runs; require two consecutive missing liveness samples before reaping a running run; call `_expire_ephemera` unconditionally + safety TTL on first `XADD` | `app/agents/runs/{worker,reaper,repository,service}.py` | Each defect has a regression test in `tests/agents/runs/` |
| **P1-9** | Thread delete ordering (§5.5): commit the row delete **before** purging checkpoints, per `purge_checkpoints`' own documented contract | `app/threads/router.py`, `app/threads/service.py` | A failed commit can no longer orphan a thread whose history is gone |
| **P1-10** | Slack robustness (§5.6): keep strong references to fire-and-forget event tasks, replace per-process webhook dedup with Redis `SET NX EX`, guard the unconditional `payload.event` dereference | `app/integrations/slack/router.py` | A malformed callback returns 200 without a retry loop; dedup holds across instances |
| **P1-11** | Buffer run SSE chunks: bounded buffer flushed by pipeline every N chunks / T ms instead of one awaited `XADD` per chunk (§3.4) | `app/agents/runs/worker.py` | A 3,000-chunk run pays ~N/32 Redis RTTs, not 3,000 |
| **P1-12** | Background-loop supervision (§2.3, high): `RunDispatcher`/reaper/scanner crashes must not leave the instance serving 200s with no execution. `PeriodicLoop(interval, tick)` base with try/except + backoff, and task liveness on the health endpoint | `app/main.py`, `app/agents/runs/{worker,reaper}.py`, `app/triggers/scanner.py` | A raising tick is logged and retried; `/health` reports loop liveness |
| **P1-13** | Trigger scanner pre-warms the model whitelist before opening the claim transaction, as `RunService.create` already does (§3.7) | `app/triggers/{service,scanner}.py` | No CDN fetch inside a transaction holding `FOR UPDATE SKIP LOCKED` row locks |
| **P1-14** | Narrow `_open_session`'s `try` to the handshake — the `yield` sits inside it, so exceptions raised by the *caller's* block get laundered into `DomainError` 500s (§5.7) | `app/mcp/client/connectivity.py` | A caller-body exception propagates unchanged; covered by a test |
| **P1-15** | `MCPServerService.update` must clean up on auth-type/URL changes — today it orphans credential rows and leaves Redis tokens issued for the old resource (§5.8) | `app/mcp/servers/service.py` | Changing auth type or URL leaves no stale credential or token |
| **P1-16** | One shared resolver behind `get_current_user` and `get_current_user_optional`: their auth precedence had diverged, so a stale cookie + valid PAT authenticated on required endpoints and read as anonymous on optional ones (§5.9) | `app/auth/dependencies.py` | Both dependencies resolve identically; covered by a test |
| **P1-17** | Langfuse: build the client lazily instead of as a module-level import side effect (a bad URL currently kills every import of `runtime.py` at startup), and `flush()` on shutdown so scale-to-zero doesn't lose trace tails (§5.10) | `app/integrations/langfuse/callback.py`, `app/main.py` | Importing `runtime.py` cannot fail on Langfuse config; traces survive shutdown |

### Phase 2 — Runtime unification

Do this **before** the deepagents 0.7 / langchain upgrades (see `framework-upgrade-assessment.md`)
— it shrinks the upgrade surface to the three middleware classes actually imported.

| ID | Task | Files | Done when |
|---|---|---|---|
| **P2-1** ⛓ blocks P2-2 | Behavioural tests for `Agent.build`/`Agent.stream` with a scripted fake chat model, plus the recursion fallback and teardown containment, so the graph actually executes under test before it is refactored (§6.2 gap 3) | `tests/agents/test_runtime.py` | The graph runs end-to-end in tests; middleware assertions are behavioural, not `isinstance` lists |
| **P2-2** | Spike: verify `FilesystemMiddleware` + `LazySandboxBackend` parity outside `create_deep_agent`, and decide what to do about deepagents' harness prompt fragments | — | Written finding: parity confirmed, and which prompt fragment (if any) to append ourselves |
| **P2-3** | **Unify `build_runnable` on `create_agent`** with one explicit middleware assembly (§1.4). Deletes the dual branch, the `PatchToolCallsMiddleware` strip-hack, and the dual `str`/`SystemMessage` prompt shape. Decide *deliberately*, for all agents, whether summarization and prompt caching stay | `app/agents/runtime.py` | One construction path; middleware is one diffable list; no sandbox-conditional behaviour fork |
| **P2-4** | Share one middleware assembly between the parent build and `ResolvedAgent.compile` | `app/agents/runtime.py` | Parent and subagent stacks differ only in documented, intentional ways |
| **P2-5** | File tracked issues for the two silent product gaps the code documents: subagent HITL approval gates are dropped, subagent sandboxes never persist | GitHub issues + comment cross-refs | A contributor adding subagent HITL finds the issue instead of silence |
| **P2-6** | Batch subagent resolution — **not** `asyncio.gather` (one shared `AsyncSession` is not concurrency-safe); batch the queries via P1-4's `RunSpec` | `app/agents/runtime.py` | Subagent resolution is O(1) queries, not O(N) sequential resolves |
| **P2-7** | Replace hand-rolled `_dicts_to_lc_messages` with `langchain_core.messages.convert_to_messages`; make `get_regeneration_checkpoint_id` stop walking the full checkpoint history | `app/agents/runtime.py` | ~30 lines deleted; regeneration is O(1) state loads |

### Phase 3 — Consolidation (PR-sized, order flexible)

| ID | Task | Files | Done when |
|---|---|---|---|
| **P3-1** | Ordered `EffectivePermission(str, Enum)` + `AgentService.require_permission(agent_id, user, at_least=...)` as the single chokepoint; replaces six hand-typed tuples and gates the currently-ungated agent mutation endpoints (§4.4) | `app/agents/core/service.py`, `app/agents/router.py`, `app/agents/models.py` | No `in ("owner", "admin", …)` tuple anywhere; every mutation endpoint gated |
| **P3-2** | `resolve_transport_auth(server, user_id, repo)` seam + a single `OAUTH_QUIRKS` table; fixes `Bearer None` and the silent unauthenticated connect; adding an auth scheme becomes 3 edits with `match` exhaustiveness instead of 8 scattered ones (§4.1, §6.1) | `app/mcp/client/{auth,factory,connectivity}.py`, `app/mcp/servers/service.py` | One dispatch site; unknown auth type raises on both paths |
| **P3-3** | Move the `OAuthAuthorizationRequired` catch from the app-global handler to the MCP seam, expose `auth_required` as a typed discriminated-union response on the endpoints whose job is connecting, then **delete** the `ExceptionGroup` registration in `main.py` (§2.4) | `app/main.py`, `app/mcp/client/{connectivity,auth}.py`, `app/mcp/servers/{router,schemas}.py`, `app/agents/toolset.py` | No `OAuthAuthorizationRequired` escapes an MCP boundary; `main.py` has no ExceptionGroup handler |
| **P3-4** | Exception handlers → one `STATUS: dict[type, int]` mapping, and use `root_cause()` in the group branch so TaskGroup-wrapped domain exceptions keep their status (§2.3, med) | `app/main.py`, `app/exceptions.py` | Six copy-paste handlers become one; a `NotFoundError` raised in a TaskGroup returns 404 |
| **P3-5** | Query slimming: bulk `DELETE … WHERE` for the five select-then-delete-each loops, drop the redundant `get_or_404` + refresh loop in mutations, `load_only` on the agents list query so multi-KB `instructions` blobs stop shipping (§3.5, §3.6) | `app/agents/core/{repository,service}.py`, `app/agents/{mcp_servers,subagents,sandboxes}/repository.py` | A one-column PATCH is ~4 round-trips; `delete_permanently` is ~6 |
| **P3-6** | Typed event envelopes: run delivery + Slack events as TypedDict/enum instead of SSE string re-parsing (§1.3, §4.2); `RunDB.error_code` column replacing exact-string `MCP_REAUTH_ERROR` matching; machine-readable HITL `block_id` with emoji as presentation only | `app/agents/{stream,runs/state,runs/models}.py`, `app/integrations/slack/{handlers,chat}.py`, `alembic/versions/` | Slack delivery does not parse our own SSE strings; rewording an error message cannot break reconnect |
| **P3-7** | Extract thread read logic from the router into the service with real `*Response` schemas; persist the `tool_call_id → checkpoint_ns` mapping at run time so `get_subagent_state` is one `aget`; pick one wire format for history; derive stable UI message ids from LangChain ids (§2.1, §3.8) | `app/threads/{router,service,serialization}.py`, `app/agents/runs/worker.py` | No checkpoint access in the router; history returned once, in one encoding |
| **P3-8** | Repository cleanup in the template modules so they teach the right habits: `AuthService`'s six raw queries, `invites`' raw cross-module selects and the `service._to_response` cross-layer call, `subagents`' raw `UserDB` select (use the existing `UserRepository.list_by_ids`) (§2.1) | `app/auth/service.py`, `app/invites/{service,router}.py`, `app/agents/subagents/service.py` | No `select(...)` outside a repository, in any module |
| **P3-9** | Collapse twin DTOs (`AgentPermissionResponse`≡`Create`, `AgentTeamsSet`≡`Response`), the thrice-copied color validator → one `Annotated` alias, the re-typed inherited field; link `BaseService`/`BaseRepository` TypeVars and let the base build its repository from a class attribute (§4.5) | `app/agents/schemas.py`, `app/service.py`, `app/repository.py` | One boilerplate line deleted per service subclass; mypy checks the generics |
| **P3-10** | Shared `ROOT_ENV` + `SettingsConfigDict` exported from `app/settings.py`, replacing 12 files each counting `.parent`s (and several mis-annotating `model_config` as pydantic's `ConfigDict`) (§4.1) | `app/settings.py` + the 12 module settings files | One `.env` resolution; config-key typos are type-checked |
| **P3-11** | Break the agents ↔ sandbox cycle: make the dependency one-directional (agents orchestrates detach-and-delete, calling down into sandbox), move the provider registry to a leaf module, delete the lazy-import cycle-breakers (§2.3) | `app/sandbox/{service,provider}.py`, `app/agents/sandboxes/` | No lazy import exists to break a cycle; imports can all move to module top |
| **P3-12** | Renames (§6.1): `model_providers/catalog.py` → `factory.py`, `mcp/client/initialize.py` → `sdk_patches.py`, `client/connectivity.py` → a domain module beside `servers/`, `create_or_update` → what it actually does, and make `_sync_tools` stop swallowing exceptions on an explicit sync | `app/model_providers/`, `app/mcp/`, `app/agents/mcp_servers/service.py` | Every module name describes its contents; an explicit sync that fails returns an error |
| **P3-13** | Whole-set-replace helper: one diff-and-upsert utility for the three hand-rolled copies (agent MCP servers, sandboxes, subagents), and stop subagents re-running 4 validation queries per item (§4.1) | `app/agents/{mcp_servers,sandboxes,subagents}/service.py`, `app/repository.py` | One implementation with one flush policy |
| **P3-14** | Extract the thrice-copied OAuth-preflight + commit stanza in `runs/router.py` into a FastAPI dependency (§4.1) | `app/agents/runs/router.py` | One copy |
| **P3-15** | Postgres test lane: a `postgres`-marked pytest lane against `docker-compose.dev.yml` covering `claim_next`'s `SKIP LOCKED`, the partial unique index, and an `alembic upgrade head` over all 47 migrations; skipped when Postgres is absent so the 4.4s zero-infra lane stays default. Plus a metadata-completeness test guarding `env.py`'s manual model-import registry (§6.2) | `tests/conftest.py`, `tests/agents/runs/`, `tests/test_migrations.py`, `.github/workflows/backend-ci.yml` | CI runs both lanes; a forgotten model import fails a test instead of emitting a table deletion |
| **P3-16** | Progressively delete Tier-B mock-mirror tests as each module is touched: `AsyncMock` sessions with `execute.side_effect` lists that hard-code query count and order, and the ~70 `assert_awaited_once_with` delegation tautologies (§6.2). Keep only orchestration-order tests that encode a real invariant | `tests/agents/core/test_service.py` and peers | Refactors fail on behaviour, not on `StopIteration` |
| **P3-18** | Stop mounting the FastMCP app at `/`: every unmatched route falls into the sub-app, which owns 404 semantics and bypasses the app's exception handlers. Mount under a prefix if the protocol allows, or gate it (§2.3) | `app/main.py`, `app/mcp/router.py` | An unknown path returns the app's own 404; handlers apply everywhere |
| **P3-17** | Small perf tail (§3.9): concurrent `MCPClientConfigFactory.build`, single token read/decrypt in `is_authorized`, `MGET` in `list_connections`, `remote_catalog.bundled()` off the async path, `GatewayTransport`'s `httpx.Client` closed, OpenSandbox polling backoff, `OpenSandbox.id` not doing IO in a property, `remote_catalog`'s ETags actually used for conditional GET (or deleted) | `app/mcp/`, `app/sandbox/`, `app/utils/remote_catalog.py` | Each item either fixed or deleted as dead |

### Explicitly out of scope

Restating §8's "what NOT to do", so a future contributor doesn't reopen it: **no DDD
migration**, **no replacing the runs runtime** with arq/taskiq/Celery, **no unifying on
`create_deep_agent`**, **no split into services/packages**. The module boundaries are
right; they need the cycles removed and the docs to match, not redrawing.
