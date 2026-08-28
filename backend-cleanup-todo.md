# Backend cleanup — progress tracker

Checklist for the plan in [`backend-design-review.md` §9](./backend-design-review.md#9-implementation-plan-task-breakdown).
The review is the specification (what and why, with `file:line` evidence); this file is
just the state. Task IDs are stable — reference them in commits and PR titles.

**Status legend:** `[ ]` not started · `[~]` partly done · `[x]` done · `[!]` blocked

Last updated: 2026-08-28

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

## Phase 1 — Hot path & stability

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
- [ ] **P1-2** `to_thread` around remaining Argon2 — **do this next.** It was written as
      the stopgap for P1-1 (§3.1b), so with P1-1 parked it *is* the mitigation: it takes
      Argon2 off the event loop for the PAT prefix scan as well as for passwords, so
      in-flight SSE streams stop stalling. No migration, no DB access, no token handling
      — entirely independent of P1-1's decision
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
