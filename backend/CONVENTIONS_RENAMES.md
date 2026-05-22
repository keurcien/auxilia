# Backend Naming Conventions — Renames Punch List

This file lists every change needed to bring the backend in line with `CONVENTIONS.md`. Each entry has the file, the before/after, and which decision it traces to.

Conventions used here:
- `path:line` refers to the location at the time of the audit. Line numbers may drift; the symbol names are what matter.
- "+ migration" means an Alembic migration is required (DB column rename or enum value change).
- "+ frontend" means matching TS/Zustand updates in `web/`.

Grouped by batch (see `CONVENTIONS.md` §1 of the original plan for execution order).

---

## Batch 1 — Pure verb / method renames (no DB migration)

### `app/repository.py` and `app/service.py`
No changes — base classes already use the canonical verbs (`get`, `create`, `update`, `delete`, `get_or_404`).

### `app/users/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `async def list(self, role=None)` | unchanged | — |
| `async def get_by_email(self, email)` | unchanged | — |

### `app/users/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_ensure_email_available` | unchanged | D6 |
| `get_user(user_id)` | `get(user_id)` | D5 |
| `get_user_by_email(email)` | `get_by_email(email)` | D5 |
| `list_users(role=None)` | `list(role=None)` | D5 |
| `create_user(data)` | `create(data)` | D5 |
| `update_user(user_id, data)` | `update(user_id, data)` | D5 |
| `update_user_role(user_id, data)` | `update_role(user_id, data)` | D5 |
| `delete_user(user_id)` | `delete(user_id)` | D5 |

### `app/users/router.py`
| Before | After | Decision |
| --- | --- | --- |
| Handler `get_user_by_email_route` | `get_user_by_email` | route §5 |
| Call sites `service.list_users(...)` | `service.list(...)` | D5 |
| Call sites `service.get_user(...)` etc. | `service.get(...)` etc. | D5 |

### `app/agents/core/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `list_with_permissions(...)` | unchanged | — |
| `get_permissions(agent_id)` | unchanged | — |
| `set_permissions(agent_id, permissions)` | unchanged | D3 note (this is a bulk-replace `set_*`, not an upsert) |
| `archive(agent)` | unchanged | — |

### `app/agents/core/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_resolve_permission(...)` | unchanged | — |
| `_assemble(...)` | unchanged | — |
| `_group_rows(...)` | unchanged | — |
| `get_agent(agent_id, ...)` | `get(agent_id, ...)` | D5 |
| `create_agent(data)` | `create(data)` | D5 |
| `list_agents(...)` | `list(...)` | D5 |
| `update_agent(agent_id, ...)` | `update(agent_id, ...)` | D5 |
| `delete_agent(agent_id, ...)` | `delete(agent_id, ...)` | D5 |
| `get_permissions(agent_id)` | unchanged | — |
| `set_permissions(agent_id, ...)` | unchanged | D3 note |
| `check_ready(agent_id, user_id)` | `describe_readiness(agent_id, user_id)` | D4 |

### `app/agents/router.py`
| Before | After | Decision |
| --- | --- | --- |
| Path `GET /{agent_id}/is-ready` handler `is_ready` | unchanged | §5 (predicate verb-in-path allowed) — but it now hits `describe_readiness` internally |
| Route function call sites for renamed service methods | use new names | D5 |

### `app/agents/mcp_servers/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `get(agent_id, server_id)` | unchanged | — (composite key fetch) |

### `app/agents/mcp_servers/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_require_server(server_id)` | `_ensure_server(server_id)` | D6 |
| `_fetch_and_save_tools(...)` | `_sync_tools(...)` or split into `_list_tools_from_mcp(...)` + `_persist_tools(...)` | D1 + D3 (fetch→list, save→create_or_update) |
| `create_or_update(agent_id, server_id, ...)` | unchanged | D3 — already canonical |
| `update(agent_id, server_id, data)` | unchanged | — |
| `delete(agent_id, server_id)` | unchanged | — |
| `sync_tools(agent_id, server_id, user_id)` | unchanged | domain verb (§2) |

### `app/agents/subagents/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `get(coordinator_id, subagent_id)` | `get(supervisor_id, subagent_id)` | D8 |
| `get_for_coordinator(coordinator_id)` | `list_for_supervisor(supervisor_id)` | D1 + D8 |
| `get_coordinator(subagent_id)` | `get_supervisor(subagent_id)` | D8 |
| `has_subagents(agent_id)` | unchanged | — |
| `is_subagent(agent_id)` | unchanged | — |
| `create(coordinator_id, subagent_id)` | `create_or_update(supervisor_id, subagent_id)` (already has check-then-create logic) | D3 + D8 |
| `delete(link)` | unchanged | — |
| `delete_all_for_agent(agent_id)` | unchanged | — |

### `app/agents/subagents/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_to_response(agent)` | unchanged | — |
| `_load_agents(ids)` | `_list_agents(ids)` | D1 |
| `load_subagents(agent_id)` | `list_subagents(agent_id)` | D1 |
| `load_all_subagent_data(agent_ids)` | `list_all_subagent_data(agent_ids)` | D1 |
| `create(...)` | `create_or_update(...)` (mirrors repo) | D3 |
| `delete_all_for_agent(agent_id)` | unchanged | — |
| All "coordinator" variable / parameter names | "supervisor" | D8 |

### `app/threads/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `get(id)` | unchanged | — |
| `get_with_agent(thread_id)` | unchanged | — |
| `list_for_user(user_id)` | unchanged | — |
| `list_for_agent(agent_id)` | unchanged | — |

### `app/threads/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `get_thread(thread_id)` | `get(thread_id)` | D5 |
| `get_thread_with_agent(thread_id)` | `get_with_agent(thread_id)` | D5 |
| `list_threads(user_id)` | `list(user_id)` | D5 |
| `list_threads_for_agent(agent_id)` | `list_for_agent(agent_id)` | D5 |
| `create_thread(data, user_id, source)` | `create(data, user_id, source)` | D5 |
| `delete_thread(thread_id)` | `delete(thread_id)` | D5 |
| Module-level `get_or_create_thread(...)` | `ThreadService.get_or_create(...)` (move onto the service) | D5 + D18 |

### `app/threads/router.py`
| Before | After | Decision |
| --- | --- | --- |
| Handler `read_thread` | `get_thread` (matches HTTP `GET`) | route §5 |
| Handler `get_threads` | unchanged | — |
| Handler `get_subagent_state` | unchanged | — (domain action, not CRUD) |
| Handler `run_stream` (route `/runs/stream`) | unchanged | route §5 (streaming RPC) |
| Handler `run_invoke` (route `/runs/invoke`) | unchanged | route §5 (RPC) |

### `app/mcp/servers/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `list()` | unchanged | — |
| `create(data)` | unchanged | — |
| `get_api_key(server_id)` | unchanged | — |
| `save_api_key(server_id, api_key)` | `create_or_update_api_key(server_id, api_key)` | D3 |
| `get_oauth_credentials(server_id)` | unchanged | — |
| `save_oauth_credentials(...)` | `create_or_update_oauth_credentials(...)` | D3 |
| `list_official()` | unchanged | — |

### `app/mcp/servers/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `get_server(server_id)` | `get(server_id)` | D5 |
| `list_servers()` | `list()` | D5 |
| `list_official_servers()` | `list_official()` | D5 |
| `create_server(data)` | `create(data)` | D5 |
| `update_server(server_id, data)` | `update(server_id, data)` | D5 |
| `delete_server(server_id)` | `delete(server_id)` | D5 |
| `reset_server(server_id)` | `reset(server_id)` | D5 |
| `handle_oauth_callback(code, state)` | unchanged | domain verb |
| `list_tools(server, user_id)` | unchanged | — |

### `app/mcp/servers/router.py`
| Before | After | Decision |
| --- | --- | --- |
| Path `{mcp_server_id}` in `/list-tools`, `/is-connected`, `/is-connected-v2` | `{server_id}` everywhere | §5 (consistency within router) |
| Handler `is_connected_v2` and its route `/is-connected-v2` | replace `is_connected` with this implementation and delete the v2 endpoint; if both versions are still needed, rename to `is_connected_streaming` (descriptive, not version-numbered) | §5 (no `-vN` in URLs) |
| Helper `get_server_or_404` in router file | move to `MCPServerService.get_or_404` (inherited from `BaseService`) | layering (CLAUDE.md) |

### `app/mcp/client/connectivity.py`
| Before | After | Decision |
| --- | --- | --- |
| `check_oauth_connected(...)` | Split into `is_oauth_connected(...)` (bool) and `probe_oauth_connection(...)` (status dict) — adopt whichever shape each caller needs | D4 |
| `check_connectivity(...)` | `probe_connectivity(...)` | D4 |
| `check_connectivity_with_refresh(...)` | `probe_connectivity_with_refresh(...)` | D4 |

### `app/mcp/utils.py`
| Before | After | Decision |
| --- | --- | --- |
| `check_mcp_server_connected(...)` | `probe_mcp_server(...)` (returns the same payload — name is the only change) | D4 |

### `app/auth/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_require_password_auth()` | `_ensure_password_auth()` | D6 |
| `_email_exists(email)` | absorb into `_ensure_email_available(email)` (already exists in `UserService`); if a standalone predicate is still needed, name it `is_email_taken(email)` | D4 + D6 |
| `_issue_token(user)` | `build_jwt_for_user(user)` (or `sign_jwt_for_user` if "sign" reads better at the call site) | D7 |
| `count_users()` | unchanged | — |
| `signin(data)` | unchanged | domain verb |
| `setup(data)` | unchanged | domain verb |
| `accept_invite(data)` | unchanged | domain verb |
| `google_signin_or_link(...)` | unchanged | domain verb |
| Class `InvalidCredentialsError` | **move to** `app/exceptions.py` | §7 |
| Class `NoInviteError` | **move to** `app/exceptions.py` | §7 |

### `app/auth/tokens/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `list_by_user(user_id)` | unchanged | — |
| `resolve_token(plaintext)` | `get_by_token(plaintext)` | D2 |

### `app/auth/tokens/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_generate_token()` | unchanged | D7 (entropy → `_generate_*`) |
| `create_token(user_id, name)` | `create(user_id, name)` | D5 |
| `list_tokens(user_id)` | `list(user_id)` (the entity is generic at the service layer; if name collisions hurt readability, keep `list_by_user(user_id)` instead) | D5 |
| `delete_token(token_id, user_id)` | `delete(token_id, user_id)` | D5 |
| `resolve_token(plaintext)` | `get_by_token(plaintext)` | D2 |

### `app/invites/repository.py`
| Before | After | Decision |
| --- | --- | --- |
| `get_by_token(token)` | unchanged | — |
| `get_pending_by_email(email)` | unchanged | — |
| `list_pending()` | unchanged | — |
| `revoke_pending_by_email(email)` | unchanged | (domain verb — soft delete via status change) |
| `set_status(invite, new_status)` | unchanged | — |

### `app/invites/service.py`
| Before | After | Decision |
| --- | --- | --- |
| `_is_usable(invite)` | unchanged | D4 (clean bool predicate) |
| `build_invite_url(token)` | unchanged | D7 |
| `create_invite(...)` | `create(...)` | D5 |
| `validate_invite(token)` | `get_by_token(token)` (returns the invite if usable; callers that want a yes/no add a separate `is_usable` predicate around it) | D2 |
| `get_pending_by_email(email)` | unchanged | — |
| `list_pending_with_inviters()` | unchanged | — |
| `revoke(invite_id)` | unchanged | domain verb |

### `app/invites/router.py`
| Before | After | Decision |
| --- | --- | --- |
| Handler `create_invite_endpoint` | `create_invite` | route §5 |
| Module-level helper `_invite_to_read` | move to `InviteService._to_response` (matches the §2 helper convention) | layering |

### `app/agents/runtime.py` (verb renames only — class rename is in Batch 2)
| Before | After | Decision |
| --- | --- | --- |
| `get_regeneration_checkpoint_id(agent, config)` | unchanged | — |
| `Agent.resolve(...)` classmethod | renamed when the class is renamed (Batch 2) | — |

---

## Batch 2 — Runtime class swap (no DB migration)

Single PR. Touches every importer of `Agent` and `AgentRuntime` from `app.agents.runtime`.

### `app/agents/runtime.py`
| Before | After | Decision |
| --- | --- | --- |
| `class Agent` (dataclass at line 68) | `class ResolvedAgent` | D10 |
| `class AgentRuntime` (line 128) | `class Agent` | D10 |
| `Agent.resolve(...)` classmethod | `ResolvedAgent.resolve(...)` | D10 |
| `Agent.compile(model)` | `ResolvedAgent.compile(model)` | D10 |
| `AgentRuntime.build(thread, db)` | `Agent.build(thread, db)` | D10 |
| `AgentRuntime.invoke(...)` | `Agent.invoke(...)` | D10 |
| `AgentRuntime.stream(...)` | `Agent.stream(...)` | D10 |
| Internal: `self.agent` (a `ResolvedAgent`) inside the new `Agent` class | consider renaming to `self.resolved` or `self.spec` so it doesn't shadow the class name | clarity |
| Internal: `self.subagents: list[Agent]` | `self.subagents: list[ResolvedAgent]` | D10 |

### Importers to update
All places that import `Agent` or `AgentRuntime` from `app.agents.runtime`. Grep before the rename to enumerate. Known call sites include:
- `app/threads/router.py` (the `/runs/stream` and `/runs/invoke` handlers)
- `app/integrations/slack/handlers.py` (or wherever Slack invocation lives)
- Tests under `tests/agents/`

For each, replace `AgentRuntime.build(thread, db)` with `Agent.build(thread, db)` and update local variable names (`runtime = ...` → `agent = ...`).

---

## Batch 3 — Field renames (Alembic migration + frontend)

One Alembic migration per row of the table below. Keep them small so each can be reviewed independently.

| Table | Before column | After column | Decision | + frontend |
| --- | --- | --- | --- | --- |
| `users` | `hashed_password` | `password_hash` | D14 | TS field rename: `hashedPassword` → `passwordHash` (or remove if not exposed) |
| `agents` | `sandbox` | `is_sandboxed` | D13 | `sandbox` → `isSandboxed` in `web/src/types/`, agent form, Zustand store |
| `agent_subagents` | `coordinator_id` | `supervisor_id` | D8 | `coordinatorId` → `supervisorId` |
| `agent_user_permissions` | enum value `user` (in column `permission`) | `member` | D9 | update `PermissionLevel` enum mirror in TS |

Migration template for the enum-value rename (D9): use `ALTER TYPE ... RENAME VALUE` in PostgreSQL (Postgres 10+), wrapped in a `do_run_migrations` block that downgrades by renaming back.

### `app/agents/models.py`
| Before | After | Decision |
| --- | --- | --- |
| `AgentDB.sandbox: bool` | `AgentDB.is_sandboxed: bool` | D13 |
| `AgentSubagentDB.coordinator_id: UUID` | `AgentSubagentDB.supervisor_id: UUID` | D8 |
| `PermissionLevel.user` enum member | `PermissionLevel.member` | D9 |
| Helper that reads `agent.sandbox and sandbox_settings.enabled` | reads `agent.is_sandboxed and sandbox_settings.enabled` (multiple sites in `runtime.py`) | D13 |

### `app/users/models.py`
| Before | After | Decision |
| --- | --- | --- |
| `UserDB.hashed_password: str \| None` | `UserDB.password_hash: str \| None` | D14 |

### Auth code paths using the renamed columns
- `app/auth/utils.py` (`hash_password`, `verify_password`) — verify the field reference, update.
- `app/auth/service.py` — any direct `user.hashed_password` access.

---

## Batch 4 — Exception consolidation

### `app/exceptions.py`
| Before | After | Decision |
| --- | --- | --- |
| `class ValidationError(DomainError)` | `class DomainValidationError(DomainError)` | D11 |
| (none) | Add `class InvalidCredentialsError(DomainError)` (moved from `app/auth/service.py`) | §7 |
| (none) | Add `class NoInviteError(DomainError)` (moved from `app/auth/service.py`) | §7 |

### `app/main.py`
Global handler block must be updated to register `DomainValidationError` (replacing `ValidationError`) and the relocated auth exceptions if they need bespoke status codes.

### Every raise site
Every `raise ValidationError(...)` and every import of `ValidationError` from `app.exceptions` becomes `DomainValidationError`. Grep across `app/` + `tests/` and replace.

### `app/auth/service.py`
Remove the local `InvalidCredentialsError` / `NoInviteError` class definitions; import them from `app.exceptions` instead.

---

## Batch 5 — Route cleanup (no DB migration; touches frontend)

### `app/mcp/servers/router.py`
- Every `{mcp_server_id}` in a path → `{server_id}`.
- Every handler parameter `mcp_server_id` matching one of those paths → `server_id` (the variable name follows the path parameter).
- `is_connected_v2`: decide between (a) replacing `is_connected` and deleting the old one, or (b) renaming `is_connected_v2` to a descriptive name like `is_connected_streaming`.

### `app/invites/router.py`
- Handler `create_invite_endpoint` → `create_invite`.

### `app/users/router.py`
- Handler `get_user_by_email_route` → `get_user_by_email`.

### Frontend axios call sites
Anywhere the frontend hits `/mcp-servers/{mcp_server_id}/...` paths, update to `{server_id}` — likely in `web/src/lib/api/mcpServers.ts` or similar.

---

## Things deliberately NOT renamed

These came up in the audit but are kept as-is per the conventions:

| Item | Why it stays |
| --- | --- |
| `WorkspaceRole` enum values (`member`/`editor`/`admin`) | Already canonical |
| `ThreadDB.id: str` (Slack timestamp) | Not a UUID by design |
| `created_by`, `invited_by` columns | D17 — past-participle verb-form FKs don't carry `_id` |
| `owner_id` column on `AgentDB` | D12 — semantic noun role |
| `set_permissions(...)` (bulk-replace) | D3 — `set_*` is a documented verb for collection replacement (distinct from `create_or_update`) |
| `archive(...)`, `revoke(...)`, `reset_*` | Domain-specific soft-delete verbs |
| `signin`, `signout`, `setup`, `accept_invite` | Domain auth verbs |
| `sync_tools`, `handle_oauth_callback` | Domain verbs |
| `encrypt_value`, `decrypt_value`, `sanitize_tool_name`, `wrap_tool_errors` | Pure-function names already canonical |
| `*Patch` schemas (not `*Update`) | Already canonical |
| `BaseRepository.get(id)`, `BaseService.get_or_404(id)` parameter name `id` | Generic-base exception — entity is unknown at this layer |
| `Toolset.resolve(...)` | D18 — `resolve` is the verb for "DB lookup + hydrate" |
| `*Factory.build(...)`, `Agent.build(...)` | D18 — `build` is for orchestration |
| `_generate_token`, `secrets.token_*` based helpers | D7 — entropy gets `_generate_*` |
| Existing `is_*` / `has_*` predicates | D4 — already correct |
| `LangGraphStreamAdapter`, `SlackStreamAdapter` | `*Adapter` suffix is canonical |

---

## Verification

After all five batches land:

```sh
cd backend && uv run ruff check .
cd backend && uv run ruff format --check .
cd backend && uv run pytest
cd backend && uv run alembic upgrade head      # against a fresh DB
cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head   # reversibility
```

Frontend:

```sh
cd web && pnpm tsc --noEmit
cd web && pnpm lint
```

Manual smoke (`make dev`):

- Sign in
- Create an agent (toggle the sandbox flag → confirm `is_sandboxed` round-trip)
- Attach an MCP server, sync tools
- Run a thread end-to-end (streaming)
- Add a subagent → confirm `supervisor_id` is persisted
- Invite a user, accept the invite
- Create + revoke a PAT

Hit every renamed code path.

---

## Order of execution

1. **`CONVENTIONS.md`** lands first (no code change, just the doc).
2. **Batch 1**: pure verb renames. Multiple commits ok, grouped by module.
3. **Batch 2**: runtime class swap. One isolated commit/PR — touches many importers but no DB.
4. **Batch 3**: field renames + Alembic migrations. One commit per migration; frontend types in the same PR.
5. **Batch 4**: exception consolidation. One commit.
6. **Batch 5**: route cleanup. One commit; frontend axios updates in the same PR.
7. Final ruff + pytest + smoke (see Verification).

Each batch should leave the app in a runnable state — no half-renames, no `# TODO rename later`.
