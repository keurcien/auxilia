# Backend Naming Conventions

This document is the source of truth for how to name things in the FastAPI backend (`backend/`). It complements `CLAUDE.md`, which describes the _architecture_ (router → service → repository → model). This one is about _names_.

If anything in this doc conflicts with code in the repo today, the code is wrong — see `CONVENTIONS_RENAMES.md` for the punch list of changes needed to bring the codebase into compliance.

---

## 1. Glossary

### Domain entities

The bare noun is the concept. Specific classes always wear a suffix that says what stage / representation they are.

| Concept                     | Suffix family                                                                                                              |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `User`                      | `UserDB`, `UserCreate`, `UserPatch`, `UserResponse`                                                                        |
| `Agent`                     | `AgentDB`, `AgentCreate`, `AgentCreateDB`, `AgentPatch`, `AgentResponse`, `ResolvedAgent`, `Agent` (the runnable — see §4) |
| `Thread`                    | `ThreadDB`, `ThreadCreate`, `ThreadPatch`, `ThreadResponse`                                                                |
| `MCPServer`                 | `MCPServerDB`, `MCPServerCreate`, `MCPServerPatch`, `MCPServerResponse`                                                    |
| `Invite`                    | `InviteDB`, `InviteCreate`, `InviteCreateDB`, `InviteResponse`                                                             |
| `PersonalAccessToken` (PAT) | `PersonalAccessTokenDB`, `PersonalAccessTokenCreate`, `PersonalAccessTokenCreateDB`, `PersonalAccessTokenResponse`         |

Rule: **never define a class with the bare noun** (`User`, `Thread`, `MCPServer`). The bare noun is reserved for prose. `Agent` is the deliberate exception — it names the runnable runtime class (§4).

### Subagent vocabulary

A parent agent that orchestrates other agents is the **supervisor**. The orchestrated agent is the **subagent**. Never "coordinator", "parent_agent", "child_agent".

### Class suffix catalogue

| Suffix        | Meaning                                                                                                | Used by                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `*DB`         | SQLModel table (`table=True`)                                                                          | `UserDB`, `AgentDB`, …                                           |
| `*Base`       | Shared column set mixed into the table + create schema                                                 | `UserBase`, `AgentBase`                                          |
| `*Create`     | Client-supplied create payload                                                                         | `UserCreate`, `AgentCreate`                                      |
| `*CreateDB`   | Server-side create payload — adds fields the client can't set (`owner_id`, `token_hash`, `expires_at`) | `AgentCreateDB`, `InviteCreateDB`, `PersonalAccessTokenCreateDB` |
| `*Patch`      | Partial update payload (all fields nullable, consumed with `model_dump(exclude_unset=True)`)           | `UserPatch`, `AgentPatch`                                        |
| `*Response`   | API response shape                                                                                     | `UserResponse`, `AgentResponse`                                  |
| `*Service`    | Business logic class — owns the `db`, raises domain exceptions                                         | `UserService`, `AgentService`                                    |
| `*Repository` | Data access class — one method per query shape                                                         | `UserRepository`, `AgentRepository`                              |
| `*Settings`   | `pydantic_settings.BaseSettings` config class                                                          | `AppSettings`, `AgentSettings`                                   |
| `*Factory`    | Builds objects from inputs                                                                             | `ChatModelFactory`, `MCPClientConfigFactory`                     |
| `*Provider`   | Provides a service or capability (OAuth, auth, …)                                                      | `WebOAuthClientProvider`                                         |
| `*Middleware` | LangChain middleware                                                                                   | `ToolErrorMiddleware`, `SubAgentMiddleware`                      |
| `*Adapter`    | Adapts one interface to another (e.g. stream protocols)                                                | `LangGraphStreamAdapter`, `SlackStreamAdapter`                   |
| `*Error`      | Domain exception (see §8)                                                                              | `NotFoundError`, `DomainValidationError`                         |
| `*Mixin`      | SQLModel column mixin                                                                                  | `UUIDMixin`, `TimestampMixin`                                    |

**Do not use**: `*Update` (we use `*Patch`), `*Schema`, `*Model`, `*DTO`, `*Payload`, `*Exception` (use `*Error`), `*Handler`, `*Manager`.

`*CreateDB` is justified only when the server adds non-trivial fields to a client-supplied payload (e.g. computed `token_hash`, derived `owner_id`). When the only server-side addition is a UUID PK, skip `*CreateDB` and let the service set the field on the DB object directly.

### Enum values

Enum values are lowercase snake*case. Multi-word values use `*` (`always*allow`), compound technical terms stay as one word (`oauth2`, `api_key`— but write`api_key`consistently with`*` for any token-like compound).

Shared role values across enums are kept in sync. `PermissionLevel` (per-agent) and `WorkspaceRole` (per-workspace) both use `member` / `editor` / `admin` — never `user` for the lowest level.

---

## 2. Verbs — one per operation

This is the canonical verb for each kind of method/function. Any other verb means: use this one instead.

### Read

| Operation                              | Verb                                                     | Returns                           | Example                                         |
| -------------------------------------- | -------------------------------------------------------- | --------------------------------- | ----------------------------------------------- |
| Fetch one by PK                        | `get(id)` (base repo), `get_by_*` (by field)             | `Entity \| None` (repo)           | `repo.get(user_id)`, `repo.get_by_email(email)` |
| Fetch one or raise 404                 | `get_or_404(id)`                                         | `Entity` (raises `NotFoundError`) | `service.get_or_404(id)`                        |
| Fetch by credential (token, hash, ...) | `get_by_token`, `get_by_hash`, …                         | `Entity \| None`                  | `repo.get_by_token(plaintext)`                  |
| Fetch many                             | `list(...)`, `list_for_*`, `list_with_*`, `list_pending` | `list[Entity]`                    | `repo.list()`, `repo.list_for_user(user_id)`    |
| Count                                  | `count_*`                                                | `int`                             | `service.count_users()`                         |
| Fetch-or-create                        | `get_or_create_*`                                        | `(Entity, bool)` or `Entity`      | `service.get_or_create_thread(...)`             |

**Reserved — do not use**: `load_*`, `fetch_*`, `resolve_*` (for DB lookups), `find_*`, `query_*`, `retrieve_*`, `select_*`.

**Note on plurals**: collection-returning methods always use `list_*`, never `get_*`. `get_for_user` returning a list is a bug; use `list_for_user`.

### Create / update / delete

| Operation                        | Verb                                          | Notes                                                    |
| -------------------------------- | --------------------------------------------- | -------------------------------------------------------- |
| Create                           | `create(...)`, `create_*`                     | Adds row(s); raises `AlreadyExistsError` on conflict     |
| Update (partial)                 | `update(...)`, `update_*`                     | Consumes `*Patch`; uses `model_dump(exclude_unset=True)` |
| Upsert                           | `create_or_update(...)`, `create_or_update_*` | Spelled out — never hidden behind `save_*` or `set_*`    |
| Delete (hard)                    | `delete(...)`, `delete_*`                     | Row removed                                              |
| Delete many                      | `delete_all_for_*`                            | E.g. `delete_all_for_agent(agent_id)`                    |
| Replace a collection             | `set_*` (e.g. `set_permissions`)              | Bulk-replace semantics, _not_ an upsert of single rows   |
| Soft delete (invite-status flip) | `revoke(...)`                                 | Invite-specific; transitions `pending → revoked`         |
| Soft delete (agent flag)         | `archive(...)`                                | Agent-specific; sets `is_archived = True`                |
| Wipe + keep row                  | `reset_*` (e.g. `reset_server`)               | Clears credentials/state, row stays                      |

**Reserved — do not use**: `save_*`, `store_*`, `persist_*` (use `create` / `update` / `create_or_update`), `remove_*` / `destroy_*` (use `delete`), `modify_*` / `edit_*` / `change_*` (use `update`), `make_*` (use `build_*`), `add_*` (use `create_*`).

### Service methods drop the entity noun

Repositories and services already name their entity through the class name. Methods do _not_ repeat it.

```python
# GOOD
class UserService(BaseService[UserDB, UserRepository]):
    async def get(self, user_id: UUID) -> UserResponse: ...
    async def get_by_email(self, email: str) -> UserResponse: ...
    async def list(self) -> list[UserResponse]: ...
    async def create(self, data: UserCreate) -> UserResponse: ...
    async def update(self, user_id: UUID, data: UserPatch) -> UserResponse: ...
    async def delete(self, user_id: UUID) -> None: ...

# BAD
class UserService(...):
    async def get_user(self, user_id): ...
    async def get_user_by_email(self, email): ...
    async def list_users(self): ...
```

Relationship and filter qualifiers stay (`list_for_user`, `list_for_supervisor`, `get_with_agent`, `list_pending`).

### Predicates and assertions

| Shape                                         | Verb                           | Returns                                          | Example                                                   |
| --------------------------------------------- | ------------------------------ | ------------------------------------------------ | --------------------------------------------------------- |
| Pure bool — state                             | `is_*`                         | `bool`                                           | `is_archived`, `is_subagent`                              |
| Pure bool — possession                        | `has_*`                        | `bool`                                           | `has_subagents`, `has_permission`, `has_code_interpreter` |
| Pure bool — capability                        | `can_*`                        | `bool`                                           | `can_edit`                                                |
| Assert / guard                                | `_ensure_*` (private)          | `None` or the asserted object; raises on failure | `_ensure_email_available`, `_ensure_server`               |
| I/O probe (network call, returns diagnostics) | `probe_*`                      | `dict` / status payload                          | `probe_connectivity`, `probe_mcp_server`                  |
| Structured status                             | `describe_*` or `get_*_status` | `dict`                                           | `describe_readiness`, `get_oauth_status`                  |

**Reserved — do not use**: `check_*` (ambiguous between predicate, assertion, and probe — pick one of the above), `validate_*` (use `_ensure_*` or `is_*`), `verify_*`, `_require_*` (use `_ensure_*`).

### Constructors of new artifacts

| Operation                     | Verb                         | Notes                                                                                     |
| ----------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------- |
| Deterministic compose         | `build_*`                    | `build_invite_url`, `build_oauth_client_metadata`, `build_jwt_for_user`. Pure function-y. |
| Entropy / cryptographic       | `_generate_*` (private)      | `_generate_token` — anything that calls `secrets.token_*` or pulls randomness.            |
| DB lookup + hydrate (factory) | `resolve(...)` (classmethod) | `ResolvedAgent.resolve(agent_id, db, user_id)`, `Toolset.resolve(...)`                    |
| Orchestrate multiple resolves | `build(...)` (classmethod)   | `Agent.build(thread, db)` — composes multiple `resolve` calls + middleware/callbacks      |

**Reserved — do not use**: `make_*`, `_issue_*` (use `build_*`), `new_*`, `from_*` (use `resolve` / `build`; future `from_spec(dict)` is allowed as a deliberate exception).

### Domain-specific verbs

These are not generic CRUD; they name a domain action and stay as-is:

- **Auth**: `signin`, `signout`, `setup`, `accept_invite`, `google_signin_or_link`
- **MCP / tools**: `sync_tools`, `reset_server`, `list_tools`, `handle_oauth_callback`
- **Misc**: `encrypt_value` / `decrypt_value`, `sanitize_tool_name`, `wrap_tool_errors`

### Serialization helpers

- `serialize_*` / `deserialize_*` — convert between formats
- `encode_*` / `decode_*` — at the wire-format layer (SSE, base64, JSON)
- `_to_response(...)` — private helper to project a `*DB` to a `*Response`. One per service module that needs it.

---

## 3. Class naming

### Service / repository pair

Every persistent entity gets exactly one `*Service` and at most one `*Repository`. The service extends `BaseService[ModelDB, Repository]` and owns the request-scoped `db`. The repository extends `BaseRepository[ModelDB]`.

Cross-module service composition happens in the service's `__init__`:

```python
class AgentService(BaseService[AgentDB, AgentRepository]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentRepository(db))
        self.subagents = SubagentService(db)  # composed, not reached into
```

A router never instantiates a repository directly; only services do.

### The Agent / ResolvedAgent split

Because agents have a persistent-store side and a runtime-execution side, two classes exist:

| Class                                        | What it holds                                                                                            | Methods                                                                    | Typical caller                                  |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------- |
| `ResolvedAgent` (in `app/agents/runtime.py`) | `config: AgentResponse` + `toolset: Toolset`                                                             | `.resolve(...)` (classmethod factory), `.compile(model)`                   | Internal: subagent compilation, `Agent.build()` |
| `Agent` (in `app/agents/runtime.py`)         | `thread`, `model`, `middleware`, `callbacks`, the resolved parent agent, `list[ResolvedAgent]` subagents | `.build(thread, db)` (classmethod factory), `.invoke(...)`, `.stream(...)` | Public: routers, integrations                   |

Public API reads:

```python
agent = await Agent.build(thread, db)
await agent.invoke(...)
async for event in agent.stream(...):
    ...
```

Subagents are typed as `list[ResolvedAgent]` — the type itself communicates that they aren't independently runnable; the parent calls `.compile(model)` on each to produce a `CompiledSubAgent` (deepagents `TypedDict`) that the `SubAgentMiddleware` consumes.

### Factory naming

- Classmethod that loads from DB: `Cls.resolve(...)`.
- Classmethod that orchestrates resolve + setup: `Cls.build(...)`.
- Free functions for building strings/objects from pure inputs: `build_*`.

Do not introduce `from_*` factory names unless you're deliberately exposing a Pydantic-AI-style declarative entry point (`Agent.from_spec(dict)` for tests is the only sanctioned case, and it doesn't exist yet).

---

## 4. Field rules

### Foreign keys

- **Default**: `{entity}_id` (`user_id`, `agent_id`, `mcp_server_id`, `thread_id`).
- **Semantic noun role**: `{role}_id` (`owner_id`, `supervisor_id`, `subagent_id`).
- **Verb-form (past participle) role**: no suffix (`created_by`, `invited_by`). This is the _only_ time an FK column doesn't end in `_id`.

Rule of thumb: ask "is the column a noun describing the relationship, or a past-tense verb describing how the row came to be?" Nouns get `_id`; verbs don't.

### Booleans

Every boolean column and every helper returning `bool` starts with **`is_`**, **`has_`**, or **`can_`**. No bare nouns for bool columns.

```python
# GOOD
is_archived: bool
has_subagents: bool
has_code_interpreter: bool
can_edit: bool

# BAD
code_interpreter: bool  # has_code_interpreter
archived: bool          # is_archived
admin: bool             # is_admin
```

Module-level helpers and method names follow the same rule.

### Timestamps

`created_at`, `updated_at` via `TimestampMixin`. No `creation_date`, `created_on`, `last_modified`, etc.

### Hash columns

`{noun}_hash` (`password_hash`, `token_hash`). Never `hashed_{noun}`.

### IDs in services / routers

- **Routes**: always prefixed: `/{user_id}`, `/{agent_id}`, `/{server_id}`, `/{thread_id}`. Never `{id}` alone in a path — it loses meaning when nested routes are added.
- **Service / repo methods**: same — `service.get(user_id)`, not `service.get(id)`. The base `BaseRepository.get(id)` and `BaseService.get_or_404(id)` keep `id` because the entity is generic at that layer.
- **Path param naming inside a router stays consistent across all endpoints in that router.** If one endpoint uses `{server_id}`, every endpoint on the same resource uses `{server_id}`.

### JSON columns

Column name is the plural of the contents (`tools` for a list of tool descriptors). No `data`, `payload`, `json_blob`.

---

## 5. Route rules

### Prefixes and methods

- Prefixes are **kebab-case plural** nouns: `/agents`, `/users`, `/mcp-servers`, `/model-providers`.
- No `/api/v1/` prefix on internal routers — versioning happens at the gateway, not in the route paths.

### Path parameters

Always prefixed (see §4): `{user_id}`, `{agent_id}`, `{server_id}`. Consistency _within a single router_ is mandatory.

### Verbs in paths

Allowed only when CRUD doesn't fit. When allowed, the verb segment is kebab-case:

| When allowed                         | Examples                                                                         |
| ------------------------------------ | -------------------------------------------------------------------------------- |
| State transition that isn't a PATCH  | `POST /agents/{agent_id}/mcp-servers/{server_id}/sync-tools`                     |
| Non-idempotent action                | `POST /mcp-servers/{server_id}/reset`, `POST /invites/accept`                    |
| Streaming / RPC                      | `POST /threads/{thread_id}/runs/stream`, `POST /threads/{thread_id}/runs/invoke` |
| Predicate (mirrors an `is_*` helper) | `GET /agents/{agent_id}/is-ready`, `GET /mcp-servers/{server_id}/is-connected`   |
| Auth-flow verbs at root              | `POST /auth/signin`, `POST /auth/signout`, `POST /auth/setup`                    |

Otherwise, stick to CRUD on the resource.

### Handler function names

The handler function name matches the route + method, **without** a `_endpoint` or `_route` suffix.

```python
# GOOD
@router.post("")
async def create_invite(...): ...

# BAD
@router.post("")
async def create_invite_endpoint(...): ...
async def create_invite_route(...): ...
```

When a route handler shadows a service method name, that's fine — the function is module-scoped inside the router file.

### Status codes

- `201 Created` on POST endpoints that create a resource.
- `204 No Content` on DELETE endpoints (no response body).
- `200 OK` is the default for GET, PATCH, and POST endpoints that return data without creating.

Set `status_code=` explicitly only when overriding a default.

### Response models

Endpoints declare `response_model=` for typed responses. Never return a `*DB` directly — project to a `*Response` first.

### Trailing slashes

Trailing slashes match what's already in the router. If the router defines `POST /`, keep `/`; if it defines `POST ""`, keep empty. Don't mix within one router.

---

## 6. Module file names

Two acceptable styles, chosen by what's in the file:

| Style                                               | When                                                         | Examples                                                                                                                                                            |
| --------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Verb / abstract noun**                            | The file is a collection of pure helper functions on a topic | `serialization.py`, `encryption.py`, `connectivity.py`                                                                                                              |
| **Concrete noun** (often a class name in lowercase) | The file is centered on one class                            | `toolset.py` (`Toolset`), `runtime.py` (`Agent`, `ResolvedAgent`), `factory.py` (`*Factory`), `repository.py`, `service.py`, `router.py`, `models.py`, `schemas.py` |

Don't create `utils.py` catch-alls. If a helper has a topic, name the file after the topic.

---

## 7. Exceptions

All domain exceptions:

- End in `*Error` (never `*Exception`).
- Inherit from `DomainError` (in `app/exceptions.py`).
- Are raised by services, translated to HTTP by the global handler in `main.py`.
- Live in `app/exceptions.py`, regardless of which module raises them. (Auth-specific exceptions like `InvalidCredentialsError`, `NoInviteError` move out of `app/auth/service.py` to keep the hierarchy in one place.)

Current map:

| Exception                 | HTTP status                                           |
| ------------------------- | ----------------------------------------------------- |
| `NotFoundError`           | 404                                                   |
| `AlreadyExistsError`      | 400                                                   |
| `DomainValidationError`   | 400                                                   |
| `PermissionDeniedError`   | 403                                                   |
| `InvalidCredentialsError` | 401                                                   |
| `NoInviteError`           | 302 (special — redirect in the OAuth callback router) |
| `DomainError` (base)      | 500                                                   |

`DomainValidationError` — not `ValidationError`. Pydantic's `ValidationError` exists for _parse-time_ failures at the HTTP boundary; ours is for _business-rule_ violations inside services. The `Domain` prefix removes the import-time ambiguity.

Routers never catch domain exceptions — the global handler does the HTTP translation. The only acceptable router-level `try/except` is when a different HTTP shape is needed (e.g. the OAuth callback catching `NoInviteError` to emit a 302 redirect).

---

## 8. Anti-patterns (cheat sheet)

A "don't" list, with the corrected version:

| Don't                                                                         | Do                                                         |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `def get_users(...)` returning a list                                         | `def list(...)` (and on the repo, `list_*`)                |
| `def get_for_agent(...)` returning a list                                     | `def list_for_agent(...)`                                  |
| `def load_subagents(...)`                                                     | `def list_subagents(...)`                                  |
| `def validate_invite(token)` returning the invite                             | `def get_by_token(token)` + `is_*` / `_ensure_*` if needed |
| `def resolve_token(plaintext)` (in PAT)                                       | `def get_by_token(plaintext)`                              |
| `def get_user_by_email(...)` on `UserService`                                 | `def get_by_email(...)`                                    |
| `def save_api_key(...)` (silent upsert)                                       | `def create_or_update_api_key(...)`                        |
| `def check_ready(...)` returning a dict                                       | `def describe_readiness(...)` (or `is_ready` if bool)      |
| `def check_connectivity(...)`                                                 | `def probe_connectivity(...)`                              |
| `def _require_server(...)`                                                    | `def _ensure_server(...)`                                  |
| `def _issue_token(user)`                                                      | `def build_jwt_for_user(user)`                             |
| `code_interpreter: bool` column                                               | `has_code_interpreter: bool`                               |
| `hashed_password: str` column                                                 | `password_hash: str`                                       |
| `coordinator_id` FK                                                           | `supervisor_id`                                            |
| `PermissionLevel.user`                                                        | `PermissionLevel.member`                                   |
| `ValidationError` (custom)                                                    | `DomainValidationError`                                    |
| `class Agent` for the runtime dataclass + `class AgentRuntime` for the runner | `class ResolvedAgent` + `class Agent` (runner)             |
| `{mcp_server_id}` and `{server_id}` in the same router                        | `{server_id}` consistently                                 |
| Handler `create_invite_endpoint(...)`                                         | Handler `create_invite(...)`                               |
| Handler `get_user_by_email_route(...)`                                        | Handler `get_user_by_email(...)`                           |
| `_endpoint` / `_route` suffix on any handler                                  | No suffix                                                  |
| `utils.py` catch-all module                                                   | Topic-named file (`encryption.py`, `serialization.py`, …)  |

---

## 9. When in doubt

1. Check the verb table (§2). If your verb isn't on it, you're using the wrong one.
2. If you genuinely need a new verb, add it to this doc with a short rationale before using it. Don't introduce vocabulary silently.
