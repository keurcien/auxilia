# Backend cleanup — progress tracker

Checklist for the plan in [`backend-design-review.md` §9](./backend-design-review.md#9-implementation-plan-task-breakdown).
The review is the specification (what and why, with `file:line` evidence); this file is
just the state. Task IDs are stable — reference them in commits and PR titles.

**Status legend:** `[ ]` not started · `[~]` partly done · `[x]` done · `[!]` blocked

Last updated: 2026-08-29

---

## Phase 0 — Guardrails ✅ complete

- [x] **P0-1** Backend CI workflow — `.github/workflows/backend-ci.yml`: `uv sync --frozen`,
      `ruff check`, `ruff format --check`, `mypy app`, `pytest` + coverage artifact, on
      `backend/**` and `catalog/**` PRs. Third-party actions pinned to full commit SHAs.
      **Its first run immediately earned its keep**: the suite could not *collect* on
      a clean checkout — `app/mcp/servers/settings.py` builds `MCPServerSettings()` at
      module scope and its `require_salt` validator raises without a salt, and every
      local run had been silently reading a developer's `.env`. The review's "green
      from a cold clone" claim (§6.2) was false; `tests/conftest.py` now supplies a
      fallback salt when neither the shell nor `.env` does, so it is true. Verified in
      a copied tree with no `.env`: 700 passed, 2 skipped (the catalog snapshot tests
      skip when `catalog/` is absent, by design)
- [x] **P0-2** Ruff `ASYNC` / `SIM` / `RUF` / `BLE001` enabled and clean.
      Notes: `ASYNC` found **nothing** — it flags known-blocking stdlib calls, not
      CPU-bound library calls, so it does *not* catch the sync-Argon2 problem (§3.1);
      P1-1/P1-2 still have to be done by hand. `RUF006` did catch §5.6's
      fire-and-forget Slack tasks. `BLE001` was enabled rather than deleting the 15
      existing `# noqa: BLE001 — reason` comments; all 17 previously-unannotated blind
      excepts now carry a documented reason. `RUF001/2/3` ignored (comments
      deliberately use typographic characters)
- [x] **P0-3** mypy configured with a **ratchet**: 115 modules checked, 50 exempted
      per-module in `[[tool.mypy.overrides]]`, none globally. Delete a line from that
      list to clean a module up; do not add lines
- [x] **P0-4** Dead code deleted: 3 sandbox settings modules + their test, the
      lorem-ipsum demo MCP tools, `ModelProviderType.ollama`, `AgentService.create`
      (and its delegation-tautology test), the `mcp/servers/encryption.py` re-export
      shim. `SubagentResponse.color` is now **populated** rather than removed (the
      agent row has a color; the contract was true-able). CORS `allow_origins=["*"]`
      → `[auth_settings.FRONTEND_URL]`, since browsers reject `*` with credentials
- [x] **P0-5** Doc drift fixed: CLAUDE.md ghost files (`agents/hitl.py`,
      `mcp/utils.py`, `mcp/servers/encryption.py`, `scripts/`, `trigger-feature-plan.md`),
      the exception table (7 rows, real statuses — `AlreadyExistsError` is 409, not 400),
      per-agent permission levels (`member`, not `user`, + team-derived membership), the
      **third** transaction regime (handlers that commit early before a long operation),
      the stale `list-tools` raw-HTTP docstring, and `pyproject.toml`'s placeholder
      description
- [x] **P0-6** `CONTRIBUTING.md` — setup, the four pre-PR commands, conventional-commit
      requirement, the layered contract, `app/users/` as the reference module, and the
      "write down why, not what" standard
- [x] **P0-7** Auth tests: 42 new tests. `tests/auth/test_utils.py` (11) and
      `tests/auth/test_dependencies.py` (31) drive the **real** dependencies with no
      overrides, so `require_editor` / `require_admin` finally execute under test.
      `app/auth/` coverage 0% → 63%; `dependencies.py` 98%, `utils.py` 100%.
      Found and fixed: a signed token with a non-UUID `sub` raised `ValueError` (a 500)
      instead of decoding to `None` (a 401)
- [x] **P0-8** `runs/SPEC.md`: the at-most-once invariant written down with its rationale
      (LLM turns are not idempotent; there is no retry, no DLQ, no backoff — a Celery
      contributor will assume otherwise) plus a Mermaid lifecycle diagram

## Phase 1 — Hot path & stability ✅ complete except P1-1 (blocked)

- [!] **P1-1** PAT lookup → SHA-256 indexed digest (+ migration) — **BLOCKED**, awaiting
      an owner decision. Blocks nothing else; it is a leaf task, so the rest of Phase 1
      proceeds without it.
      *Decided so far:* clean cut (no dual verify-then-rehash code path), but existing
      tokens are to be **preserved by manual backfill** rather than invalidated.
      *Why it can't just be done:* the migration cannot backfill. `token_hash` is
      Argon2id (one-way, salted) and the plaintext is never stored, so no digest is
      derivable from the DB. A row can only gain a digest from someone holding the
      plaintext.
      *Agreed shape:* migration 1 adds nullable `token_sha256` + unique index and
      **keeps** `token_hash`; a backfill script reads the token from stdin (never argv
      — shell history and `ps`), locates the row by `prefix`, Argon2-verifies it against
      the surviving `token_hash`, and only then writes the digest; migration 2 drops
      `token_hash` + the `prefix` index and deletes rows still NULL. Between the two,
      a NULL digest fails closed — no window where a stale token authenticates.
      *To unblock, need:* (a) which database (dev vs production; production wants a
      `pg_dump -t personal_access_tokens` first, since migration 2 is irreversible),
      and (b) the owner to run the backfill script. The token must not be pasted into
      a session transcript.
- [x] **P1-2** `to_thread` around remaining Argon2. `verify_password` /
      `get_password_hash` are now `async` and hand the hash to `asyncio.to_thread`, so
      every Argon2 call in the codebase is off the event loop: password signin/signup,
      PAT minting, and — the one that mattered — the PAT prefix scan on every Bearer
      request, which used to block the loop once *per candidate*. Making the functions
      async rather than adding wrappers means a missed call site is an unawaited
      coroutine, not a silent regression; the five call sites are in `auth/service.py`
      (3), `auth/tokens/service.py` and `auth/tokens/repository.py`.
      Guarded by `test_hashing_does_not_block_the_event_loop`, which runs a heartbeat
      coroutine alongside a hash and asserts it kept ticking — verified to fail
      (`assert 0 > 1`) when the `to_thread` is removed. 703 passed, ruff and mypy clean.
      **Still true after this:** the prefix scan is off-loop but remains sequential,
      one Argon2 verify per prefix collision. That is the part P1-1 deletes; with
      12-char prefixes over `secrets.token_urlsafe(32)` a collision is not a practical
      concern, so this is a latency footnote, not a queue
- [x] **P1-3** `TokenStorageFactory` on the shared Redis client. The factory built a
      fresh `ConnectionPool` in its constructor and was constructed *per call* at eight
      sites (`connectivity.py` ×3, `factory.py`, `servers/service.py` ×4), so every
      readiness probe, is-connected poll, agent build and OAuth callback leaked a pool
      that nothing ever closed. It now borrows `app.redis_client.get_redis()` — the
      lifespan-managed client — with `redis` injectable for tests. `grep` confirms the
      done-when: the only `Redis(` in `app/` is the one in `redis_client.py`.
      Also gone: `RedisTokenStorage`'s `host="localhost", port=6379, db=0` default
      constructor args (the deployment trap the review named — they silently ignored
      `REDIS_PASSWORD` and pointed at the wrong host), now a required injected `redis`;
      and its unused `aclose()`, which post-change would have closed the app-wide
      client out from under everything else. Covered by
      `test_factory_borrows_the_app_wide_client_instead_of_opening_a_pool`.
      704 passed, ruff and mypy clean
- [x] **P1-4** `AgentRepository.get_run_spec` → `RunSpec`. New leaf module
      `app/agents/run_spec.py` (`RunSpec` / `AgentSpec` / `SandboxSpec`) carrying DB
      rows, not response DTOs — the run path has no business depending on API response
      assembly. `get_run_spec` fills it in **three flat queries** for a graph of any
      width: one outer-joined select returning the parent *and* its direct subagent rows
      (the link row's `created_at` rides along so subagent order is stable), one `IN` for
      all `AgentMCPServerDB` bindings, one delegated to
      `AgentSandboxRepository.list_for_agents`. `SandboxSpec` carries the joined
      `SandboxDB` row, which is what lets P1-5 drop the re-fetch.
      **Needed a real test lane to prove anything**: query count is the contract and a
      mocked session cannot observe it. `tests/agents/core/conftest.py` now stands up a
      SQLite engine with a statement counter — two accommodations make the Postgres
      schema loadable (a `JSONB`→`JSON` DDL rendering for SQLite; tables created by
      walking the FK closure rather than the whole metadata, which carries Postgres-only
      columns elsewhere). 11 tests in `test_run_spec.py`, including a parametrized
      `test_cost_is_flat_in_the_number_of_subagents` over N = 0, 1, 5
- [x] **P1-5** Consume `RunSpec`. `Agent.build` does one `get_run_spec` for the whole
      graph; `ResolvedAgent.resolve` now takes an `AgentSpec` instead of an agent id, so
      resolving a subagent costs **zero** further agent queries, and `_resolve_sandbox`
      became synchronous — it reads the row the same query already joined instead of
      re-fetching it. `collect_run_bindings` is a projection of `RunSpec`
      (`all_mcp_bindings`), which fixes the (1+N)×~5 on the endpoint the frontend
      *polls*. `runtime.py` no longer imports `AgentService`, `AgentResponse` or
      `SandboxRepository` — the review's stated done-when.
      `Toolset.prepare` is retyped `Sequence[AgentMCPServerBase]` (the column set shared
      by the row and its DTO — it only ever read `mcp_server_id` and `tools`), so the run
      path passes rows and the API paths keep passing DTOs.
      Subagent resolution stays sequential *on purpose* — one `AsyncSession` is not
      concurrency-safe, and the review says so; what made it expensive was the per-agent
      read, which is now gone.
      The 8 readiness/binding tests in `tests/agents/core/test_service.py` were rebuilt
      on real `RunSpec` dataclasses instead of duck-typed `MagicMock`s (the rules turn on
      `tools is None` and on parent/subagent bindings staying separate — a mock satisfies
      either reading), plus 2 new ones for the missing-agent path. 717 passed, ruff and
      mypy clean.
      *Not covered by this task:* `describe_readiness` still returns a constant
      `"disconnected"` status and probes sequentially — that is P1-6
- [x] **P1-6** One memoized, concurrent, fail-open `probe_authorization` in
      `app/mcp/client/connectivity.py`, replacing the sequential fail-loud copy in
      `describe_readiness` and the concurrent one in `ensure_mcp_authorized`. Also fixed
      `describe_readiness` returning a constant `"disconnected"` status even when
      everything was connected — it disagreed with the `ready` flag beside it.
      **Only positives are memoized** (Redis, 30s TTL). Caching a negative would leave a
      user who has just finished the OAuth popup reading as disconnected for the length
      of the TTL, and a negative is already the cheap case — no stored token means the
      probe returns without network work. The cost is the other direction: a token
      revoked at the IdP reads as authorized for ≤30s, which the code says out loud.
      A cache outage degrades to probing, never to failing — this is the polled endpoint.
      8 tests in `tests/mcp/client/test_connectivity.py`, including a real concurrency
      assertion (peak in-flight == 3, not just "gather was called").
      **Also required**: an autouse `fake_shared_redis` fixture in `tests/conftest.py`.
      Once readiness reaches the shared client, any test that walks that path would
      otherwise connect to whatever sits on localhost:6379 — green on a developer's
      machine, hanging or erroring in CI
- [x] **P1-7** `MCPServerRepository.list_by_ids`. The review named two raw
      `select(MCPServerDB).where(id.in_(...))` outside `app/mcp/servers/`; there were
      **three** — `agents/core/service.py`, `agents/runs/service.py` and
      `agents/toolset.py`. All three now call the repository, which short-circuits an
      empty id set (`IN ()` is a round-trip for a known-empty answer, and every caller
      reaches it that way whenever an agent binds no servers). `grep` confirms the
      done-when: no `select(MCPServerDB)` outside `app/mcp/servers/`
- [x] **P1-8** Runs-runtime defects §5.1–5.4. Each has a regression test that was
      **verified to fail** with its fix reverted (the reaper had no tests at all before
      this; `tests/agents/runs/test_reaper.py` is new).
      - *§5.1 heartbeat* — every tick is now wrapped. One transient Redis error used to
        kill the loop silently, after which liveness expired and the reaper finalized a
        healthy streaming run as `error`.
      - *§5.2 queued-run reaping* — new `DispatcherLiveness` (`run:dispatchers:alive`,
        one shared key). Stuck-`pending` runs are reaped **only while no dispatcher in
        the cluster is alive**. Crucially the key is stamped from an *independent* task,
        not the claim loop: that loop blocks on `_semaphore.acquire()` when saturated,
        i.e. it goes silent exactly in the backlog case being fixed.
        Accepted trade-off, stated in the code and the SPEC: a dispatcher that is alive
        but wedged leaves pending runs un-reaped. That is P1-12's problem, and failing
        to reap is far cheaper than killing runs that were about to run.
      - *§5.3 Redis restart* — death must be observed on two consecutive sweeps
        (`_suspect` set). A restart drops every liveness key at once; the old
        single-sample rule would mass-reap a whole cluster of healthy streaming runs.
      - *§5.4 stream leak* — `_expire_ephemera` is now unconditional in `finalize`
        (`thread_id is None` includes "the thread was deleted mid-run and CASCADEd the
        row away", and nothing will ever finalize that run again), **plus** a safety TTL
        stamped on the event log's first `XADD` and pushed out by the worker heartbeat,
        so a long or uncapped run never expires its own live stream.
      Also: `RunWorker._stop` became a module-level `_cancel` (the dispatcher needs it
      too), and the SPEC's storage table + reaper section document the new key and both
      new rules. 743 passed.
      *Test-lane notes for whoever touches these next:* the SQLite lane stores
      `DateTime(timezone=True)` as **naive UTC**, and `updated_at` carries
      `onupdate=func.now()` so it cannot be backdated by an UPDATE. The reaper tests
      therefore drive `now` **forward** and use a `_db_now()` helper — a plain
      `datetime.now()` is local time and makes every young run look stale. The
      background-task tests use a bounded `_until` helper: with a plain `while`, the
      regression they guard (the task dying) would hang the suite instead of failing it
- [x] **P1-9** Thread delete ordering. `DELETE /threads/{id}` purged LangGraph
      checkpoints *first* and left the row delete to the request commit — the exact
      reverse of `purge_checkpoints`' own documented contract, so a failed commit left a
      thread whose entire history was irrecoverably gone. Now: delete the row, `commit`
      (an instance of the documented third transaction regime, with the reason in a
      comment), then purge. The other direction fails safe — a purge that errors leaves
      orphaned checkpoints, which is invisible and reclaimable.
      Covered by `test_delete_commits_the_row_before_purging_checkpoints` (verified to
      fail on the old ordering) plus a 403 test; the endpoint had **no** tests before.
      *Residual, deliberately not expanded into:* `AgentService.delete_permanently`
      purges after all DB deletes have *flushed* but still before the request commit, so
      it keeps a narrower version of the same window. Its ordering is asserted by an
      existing test and fixing it means committing mid-service, which changes that
      method's contract — worth doing under P3-5 when that method is opened anyway
- [x] **P1-10** Slack: strong task references, Redis `SET NX EX` dedup (was per-process,
      so a retry on a second instance ran the agent twice), Optional-event guard.
      `app/integrations/slack/router.py` rewritten; 9 tests in
      `tests/integrations/slack/test_router.py` (the module had none)
- [x] **P1-11** `BufferedEventPublisher` in `app/agents/runs/events.py` coalesces SSE
      chunks into pipelined appends. Bounded on **both** axes, and the second one is the
      one that matters: chunks (32) caps memory and pipeline size, delay (50ms, enforced
      by a background flusher) caps *latency*. These chunks are the tokens a user watches
      appear, so a count-only buffer would hold the tail of a slow response until enough
      tokens arrived — exactly backwards. Flush errors are carried, not swallowed: the
      next `publish`/`aclose` re-raises, so a Redis that has gone away still fails the
      run instead of silently dropping output.
      **The first version of the test proved nothing** — it counted calls to
      `publish_many`, which is the method under test. Replaced by a `count_appends`
      fixture counting *client-level* `xadd` calls (buffered writes go through
      `pipeline.xadd`, which costs nothing until `execute()`), plus a worker-level test
      that a 50-chunk run makes exactly 1 direct append (the end sentinel). Both verified
      to fail when the buffer is bypassed
- [x] **P1-12** New `app/background.py`: `PeriodicLoop` (supervised tick with
      exponential backoff, capped at 60s) + a `LoopHealth`/`LoopRegistry` pair, and a
      **new `GET /health`** returning 503 when a loop has stopped ticking. The app had no
      health endpoint at all.
      `RunReaper` and `TriggerScanner` now drive their tick through `PeriodicLoop`; they
      already caught per-tick exceptions, so what they actually gained is backoff (a
      persistent failure used to be a tight error-logging spin) and liveness reporting.
      `RunDispatcher` is **not** a `PeriodicLoop` and doesn't pretend to be — it blocks on
      its semaphore, so it is not periodic. It publishes the same `LoopHealth` and got its
      loop body wrapped, which is the actual §2.3 defect: a raise there killed it for
      good while the instance kept serving 200s.
      Both halves are needed and the module says why: supervision cannot save a loop from
      a bug in the supervisor, a cancellation, or a `BaseException`, so liveness is
      published rather than assumed. A stopped or never-started loop counts as healthy —
      `RUN_DISPATCHER_ENABLED=false` is a supported deployment, not a degraded one.
      15 tests; supervision ones verified to fail without it. SPEC's deployment section
      now says to point the platform health check at `/health`.
      **This also closes P1-8's stated trade-off** (a wedged-but-alive dispatcher leaves
      pending runs un-reaped): a wedged dispatcher now fails `/health` and gets recycled
- [x] **P1-13** `claim_and_enqueue` warms the model whitelist before `claim_due`, as
      `RunService.create` already did. Sharper version of the same problem there:
      `is_available` runs *inside* the claim transaction, which holds
      `FOR UPDATE SKIP LOCKED` locks on every claimed trigger row, so a cold catalog cache
      meant a multi-second CDN fetch with those locks held. `claim_and_enqueue` had no
      tests; it has an ordering test now (verified to fail without the pre-warm)
- [x] **P1-14** `_open_session`'s `yield` moved out of the `except Exception` wrapper.
      Any exception raised by the *caller's* `async with` body travelled back through the
      generator and got laundered into a `DomainError` — a 500 carrying someone else's
      message. 4 tests pin the boundary: a caller-body `PermissionDeniedError` propagates
      unchanged (verified to fail with the old shape), a failing `list_tools` is still
      wrapped, and `OAuthAuthorizationRequired` still passes through unwrapped so
      `test_connection` can turn it into an `oauth_required` result
- [x] **P1-15** `MCPServerService.update` purges what an edit invalidates, via a new
      `_purge_invalidated_state` and `MCPServerRepository.delete_credentials`.
      **Two triggers with deliberately different blast radii**, which is the judgement
      call in this task:
      - *URL changed* → purge all per-user Redis state (tokens, DCR registration, cached
        AS metadata — all issued for the old resource; a surviving refresh token is worse
        than none, because `is_authorized` keeps reporting the user connected). Admin-
        entered credential rows are **kept**: a static client id/secret is configuration
        someone typed, and re-pointing a server at a new path of the same provider must
        not silently discard it.
      - *auth type changed* → the same Redis purge **plus** the credential row for the
        scheme being left, which is dead config (`list_responses` already had to gate
        `oauth_client_id` on the current auth type precisely because it could linger).
      Redis purging is best-effort — a cache outage must not stop an admin fixing a
      server; the cost of a miss is a stale token the next authorization overwrites.
      5 tests including "renaming purges nothing"; 3 verified to fail without the fix
- [x] **P1-16** One shared resolver behind `get_current_user` /
      `get_current_user_optional` (§5.9) — the precedence had diverged; covered by
      `test_stale_cookie_plus_valid_bearer_resolves_the_bearer_user`
- [x] **P1-17** Langfuse client built lazily and memoized, with construction failures
      caught: a bad base URL used to take down every import of `runtime.py` at startup,
      for an optional integration. `flush_langfuse()` runs in the lifespan teardown (via
      `to_thread` — the SDK's flush is blocking and this is the loop's last breath) so
      scale-to-zero stops losing trace tails.
      `app/integrations/langfuse/__init__.py` re-exported the old module-level constant,
      so it had to change too — that re-export was itself part of the eager-import
      problem. 7 new tests

## Phase 2 — Runtime unification (before the deepagents/langchain upgrades)

- [ ] **P2-1** Behavioural `Agent.build`/`stream` tests with a scripted fake model — *blocks P2-3*
- [ ] **P2-2** Spike: `FilesystemMiddleware` + `LazySandboxBackend` parity outside `create_deep_agent`
- [ ] **P2-3** Unify `build_runnable` on `create_agent` + explicit middleware list
- [ ] **P2-4** Share one middleware assembly with `ResolvedAgent.compile`
- [ ] **P2-5** File issues for subagent HITL + subagent sandbox persistence gaps
- [ ] **P2-6** Batch subagent resolution (queries, not `gather`)
- [ ] **P2-7** `convert_to_messages` + O(1) regeneration checkpoint lookup

## Phase 3 — Consolidation (order flexible)

- [ ] **P3-1** `EffectivePermission` enum + `require_permission` chokepoint; gate ungated endpoints
- [ ] **P3-2** `resolve_transport_auth` + `OAUTH_QUIRKS`; fix `Bearer None` + silent unauth connect
- [ ] **P3-3** Catch `OAuthAuthorizationRequired` at the MCP seam; delete the global ExceptionGroup handler
- [ ] **P3-4** Exception handlers → status mapping + `root_cause` in the group branch
- [ ] **P3-5** Bulk deletes, drop redundant refetches, `load_only` on the list query
- [ ] **P3-6** Typed event envelopes + `error_code` column + machine-readable HITL block ids
- [ ] **P3-7** Thread reads into the service; O(1) subagent state; one history encoding; stable message ids
- [ ] **P3-8** Repository cleanup in `auth` / `invites` / `subagents` (the modules that get copied).
      `app/auth/service.py` is still at 24% coverage and 6 raw queries — do the cleanup
      and the tests together
- [ ] **P3-9** Collapse the twin DTOs, the thrice-copied color validator → one
      `Annotated` alias, and let the base build its repository from a class attribute.
      **Also still open: making `BaseRepository.get`'s `self.model.id` statically
      checkable.** An attempt to do it by binding `ModelType` to `BaseDBModel` was
      reverted (cubic review on #297): `ThreadDB` and `RunDB` are `TimestampMixin,
      SQLModel` with **string** primary keys by design — their ids travel through Redis
      keys, SSE headers and URL paths — so 2 of the 14 repositories legitimately fail
      that bound, and `get_or_404`'s `UUID | str` is load-bearing for the thread path,
      not laziness. Doing this properly needs a shared "has an id" ancestor spanning
      both PK conventions, which touches table definitions. `# type: ignore[attr-defined]`
      marks the one unchecked line meanwhile
- [x] **P3-10** Shared `ROOT_ENV` / `settings_config()` in `app/settings.py`, replacing 9
      files that each counted `.parent`s to find `.env` and annotated `model_config` as
      pydantic's `ConfigDict` — the wrong TypedDict, which is why a mistyped settings
      key was invisible. Now `SettingsConfigDict` + `Unpack`, so it is type-checked
- [ ] **P3-11** Break the agents ↔ sandbox import cycle
- [ ] **P3-12** Renames (`catalog.py`, `initialize.py`, `connectivity.py`, `create_or_update`);
      `_sync_tools` stops swallowing — *marked in code as `FIXME(P3-12)` at
      `app/agents/mcp_servers/service.py:61`*
- [ ] **P3-13** One whole-set-replace helper for the three hand-rolled diffs
- [ ] **P3-14** Extract the thrice-copied OAuth-preflight dependency in `runs/router.py`
- [ ] **P3-15** Postgres test lane (`SKIP LOCKED`, partial index, migrations) + metadata-completeness test
- [~] **P3-16** Tier-B mock-mirror tests: deleted the one orphaned by P0-4
      (`test_create_agent_delegates_to_repository`). The remaining ~70
      `assert_awaited_once_with` tautologies in `tests/agents/core/test_service.py` go
      as their modules get touched
- [ ] **P3-17** Perf tail (§3.9 items)
- [ ] **P3-18** Stop mounting the FastMCP app at `/` (§2.3)

---

## Review follow-ups on PR #299 (cubic)

cubic found 16 issues on the Phase 1 PR, and the important ones were real —
including two flaws inside the P1-8 fixes themselves and one self-inflicted
outage risk. Recorded here because they are the kind of mistake that recurs:

- **A fix can reintroduce the bug it was fixing.** P1-8's unconditional
  `_expire_ephemera` (§5.4) cleared the liveness key of a run that was *still
  running* whenever a guarded finalize lost a race with a dispatcher claim —
  handing the reaper a fake dead worker, which is precisely what §5.3's
  two-sample rule exists to prevent. Now gated on the row being absent or
  terminal.
- **A health check can be the outage.** P1-12 ticked dispatcher health from the
  claim loop, which blocks on the semaphore for the whole length of an agent
  turn. A fully occupied dispatcher went stale in ~63s, so `/health` 503'd and
  the platform would recycle a healthy, busy worker mid-run. Health now rides
  the liveness heartbeat, which runs on its own timer.
- **The two-sample rule had to apply to both reap paths.** "No dispatcher alive"
  is a missing Redis key too, so a restart made the reaper kill the whole
  pending queue on one sample. Also: a sweep that raised part-way left
  `_suspect` stale, so the *next* single sample could reap — the error path
  quietly restored single-sample behaviour.
- **Cancelling a task can destroy data it already took.** The event buffer's
  `_flush_locked` empties the buffer before awaiting the write, so `aclose`
  cancelling mid-write lost the tail of a run. The flusher is now asked to stop
  and awaited, never cancelled.
- **Fail-open only catches raised errors.** The `probe_authorization` cache had
  no deadline, so a stalled Redis would hang the polled endpoint rather than
  degrade. Every cache round trip is now bounded.
- **A cache must live where the invalidators can find it.** The probe cache key
  sat outside the `mcp:{user}:{server}:*` layout that `clear_server_data` scans,
  so a revoked connection or a changed server URL left it reporting authorized.
- **Two of my own tests proved nothing.** The dispatcher-liveness test deleted
  the key by hand and would have passed against a `SET` with no expiry; the
  subagent-ordering test asserted insertion order that the query never
  guaranteed (`created_at` is the transaction timestamp, so siblings tie).
- `/health` is unauthenticated, so it now reports an exception *type*, never a
  repr that could carry a DSN or token.

## Process note: the mypy ratchet can hide a regression in a base class

`app/repository.py` and `app/service.py` are checked, but most of their *subclasses*
are on the ignore list, so a change to a shared base class is only verified against the
minority of modules that are checked. That is exactly how the reverted `BaseDBModel`
bound above passed CI: mypy was green, and lifting the ratchet on three modules showed
a `type-var` violation and a Liskov violation immediately.

**When you change anything in `app/repository.py`, `app/service.py`, `app/models.py` or
`app/exceptions.py`, re-run mypy with the override list temporarily emptied** and read
what appears. It will be noisy — that noise is the 50 modules still queued for cleanup —
but a new `type-var`, `override` or `Liskov` line among it is yours.

## Catalog drift (resolved)

The two `test_publishable_copy_matches_bundled_snapshot` tests were failing because
edits to the root `catalog/*.yaml` (the CDN-uploaded copies) had never been copied to
the bundled snapshots under `backend/app/`. Both pairs are now synced and the suite is
fully green (702 passed). Added `make sync-catalog` so the copy is one command instead
of two paths to remember — run it after editing anything under `catalog/`.

## Out of scope (decided, do not reopen)

No DDD migration · no replacing the runs runtime with a generic queue · no unifying on
`create_deep_agent` · no split into services/packages. See §8 "What NOT to do".
