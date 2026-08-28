# Backend cleanup — progress tracker

Checklist for the plan in [`backend-design-review.md` §9](./backend-design-review.md#9-implementation-plan-task-breakdown).
The review is the specification (what and why, with `file:line` evidence); this file is
just the state. Task IDs are stable — reference them in commits and PR titles.

**Status legend:** `[ ]` not started · `[~]` partly done · `[x]` done

Last updated: 2026-08-28

---

## Phase 0 — Guardrails ✅ complete

- [x] **P0-1** Backend CI workflow — `.github/workflows/backend-ci.yml`: `uv sync --frozen`,
      `ruff check`, `ruff format --check`, `mypy app`, `pytest` + coverage artifact, on
      `backend/**` and `catalog/**` PRs
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

## Phase 1 — Hot path & stability

- [ ] **P1-1** PAT lookup → SHA-256 indexed digest (+ migration) — *the single biggest
      latency win left; Argon2 on the event loop stalls in-flight SSE streams*
- [ ] **P1-2** `to_thread` around remaining Argon2 (passwords)
- [ ] **P1-3** `TokenStorageFactory` on the shared Redis client
- [ ] **P1-4** `AgentRepository.get_run_spec` — *blocks P1-5, P2-6*
- [ ] **P1-5** Consume `RunSpec` in `runtime.py` / `collect_run_bindings` (drops the triple resolution)
- [ ] **P1-6** One memoized, concurrent, fail-open `probe_authorization`
- [ ] **P1-7** `MCPServerRepository.list_by_ids` — no raw cross-module selects in services
- [ ] **P1-8** Runs-runtime defects §5.1–5.4 (heartbeat, queued-run reaping, Redis restart, stream leak)
- [ ] **P1-9** Thread delete ordering (commit before purge)
- [x] **P1-10** Slack: strong task references, Redis `SET NX EX` dedup (was per-process,
      so a retry on a second instance ran the agent twice), Optional-event guard.
      `app/integrations/slack/router.py` rewritten; 9 tests in
      `tests/integrations/slack/test_router.py` (the module had none)
- [ ] **P1-11** Buffer run SSE chunks into pipelined `XADD`s
- [ ] **P1-12** Background-loop supervision + liveness on `/health`
- [ ] **P1-13** Trigger scanner pre-warms the whitelist outside the claim txn
- [ ] **P1-14** Narrow `_open_session`'s `try` to the handshake (§5.7)
- [ ] **P1-15** `MCPServerService.update` cleans up on auth-type/URL change (§5.8)
- [x] **P1-16** One shared resolver behind `get_current_user` /
      `get_current_user_optional` (§5.9) — the precedence had diverged; covered by
      `test_stale_cookie_plus_valid_bearer_resolves_the_bearer_user`
- [ ] **P1-17** Langfuse: lazy client + `flush()` on shutdown (§5.10)

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
- [~] **P3-9** **TypeVars linked** — `BaseRepository`/`BaseService` are now bound to
      `BaseDBModel` instead of `SQLModel` (mypy proved `.id` was unchecked), and
      `get_or_404`'s dishonest `UUID | str` narrowed to `UUID`. Still to do: collapse
      the twin DTOs, the thrice-copied color validator → one `Annotated` alias, and
      letting the base build its repository from a class attribute
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

## Catalog drift (resolved)

The two `test_publishable_copy_matches_bundled_snapshot` tests were failing because
edits to the root `catalog/*.yaml` (the CDN-uploaded copies) had never been copied to
the bundled snapshots under `backend/app/`. Both pairs are now synced and the suite is
fully green (702 passed). Added `make sync-catalog` so the copy is one command instead
of two paths to remember — run it after editing anything under `catalog/`.

## Out of scope (decided, do not reopen)

No DDD migration · no replacing the runs runtime with a generic queue · no unifying on
`create_deep_agent` · no split into services/packages. See §8 "What NOT to do".
