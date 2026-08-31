# CLAUDE.md

## Project Overview

auxilia is an open-source web MCP client, designed for users and companies to host and configure their MCP-powered AI assistants. auxilia only supports remote MCP servers. The key idea is that all context is provided to LLMs through MCP (skills, semantic search, web search, etc.), keeping auxilia as simple as possible.

Core features are MCP and agent management:

- **MCP**: workspace admin users can add MCP servers to workspace. Workspace MCP servers are then available to all users, to be bound to any workspace agent.
- **Agent**: an agent is defined by instructions and MCP tools. Tools can be individually configured to be disabled or to require user approval (Human-In-The-Loop).
- **Trigger**: a scheduled agent run — name + instructions bound to one agent and a model, on a cron + timezone schedule. Each firing creates a thread (`source=trigger`) and a background run on the durable runtime, executed as the trigger's owner (their MCP credentials). Owned by a user; created by workspace editors; pause/unpause via `is_active`.

External integrations:

- **Slack**: invoke workspace agents from Slack.
- **Langfuse**: monitor costs, LLM generations and tool calls.

## Backend conventions

### Layered architecture

Every backend feature follows `router → service → repository → model`. Each layer has a single responsibility:

- **Router** (`router.py`) — HTTP surface. Declares the FastAPI endpoints, binds auth dependencies, shapes the response. No DB access, no branching on domain rules.
- **Service** (`service.py`) — business logic. Inherits `BaseService[ModelDB, Repository]` (`app/service.py`), owns the request-scoped `db`, raises domain exceptions, and delegates IO to its repository. Cross-module orchestration (e.g. `AgentService` using `SubagentService`) happens here.
- **Repository** (`repository.py`) — SQL. Inherits `BaseRepository[ModelDB]` (`app/repository.py`), which provides `get / create / update / delete` for anything that subclasses `BaseDBModel`. Subclasses add one method per query shape (e.g. `get_by_email`, `list_with_permissions`). Never raises domain exceptions — returns `None` / `[]`.
- **Model** (`models.py`) — SQLModel table definitions. Inherit `BaseDBModel` (UUID PK + `created_at` / `updated_at` timestamps). For join tables skip the UUID and use `(TimestampMixin, SQLModel, table=True)`.
- **Schema** (`schemas.py`) — request/response DTOs.

Keep these layers honest. Don't write `db.execute(select(...))` in a router or in a service — lift it into a repository method named after *what* it returns. Don't catch `NotFoundError` in a service just to rewrap it — let it bubble through the global handler in `main.py`.

### Naming

- `*DB` — SQLModel table (`UserDB`, `AgentDB`, `AgentMCPServerDB`)
- `*Base` — shared column set mixed into both the table and the create schema (`AgentBase`, `UserBase`)
- `*Create` — client-supplied create payload
- `*CreateDB` — server-side create payload (adds fields like `owner_id`, `token_hash`, `expires_at`)
- `*Patch` — optional partial-update payload (all fields nullable, consumed with `model_dump(exclude_unset=True)`)
- `*Response` — API response shape. Never return a `*DB` directly; always project to a schema so relations and DB-only fields don't leak.

### Transactions

`get_db` (in `app/database.py`) runs one transaction per HTTP request: it commits on success, rolls back on any exception. Service methods should use `await self.db.flush()` when they need a server-generated value (PK, timestamp) and never call `self.db.commit()`.

There are three documented exceptions:

1. **Out-of-request code** manages its own transaction — Slack handlers, the run
   worker, the reaper and the trigger scanner use `AsyncSessionLocal()` directly
   (see `get_or_create_thread`).
2. **Request handlers that hand off to a long-lived operation commit early, on
   purpose.** The run endpoints (`agents/runs/router.py`) and
   `TriggerService.claim_and_enqueue` finish their DB work, `await db.commit()`,
   and only then start streaming or open their own sessions — holding a pooled
   connection for the length of an agent run risks pool starvation. Each such
   commit carries a comment saying why; if you add one, so should yours.
3. **Request handlers commit before a non-rollbackable side effect.**
   `DELETE /threads/{id}` and `DELETE /agents/{id}/permanent` delete their rows,
   `await db.commit()`, and only then purge LangGraph checkpoints — those live on a
   separate auto-committed connection, so purging first and then failing to commit
   would leave a row whose entire history is irrecoverably gone. The service does the
   deletes and *returns the thread ids*; it never purges. Past the commit the purge is
   logged rather than raised: the operation succeeded, and orphaned checkpoints are
   invisible and reclaimable.

### Domain exceptions

Services raise exceptions from `app/exceptions.py`:

| Exception | HTTP status |
| --- | --- |
| `NotFoundError` | 404 |
| `DomainValidationError` | 400 |
| `PermissionDeniedError` | 403 |
| `InvalidCredentialsError` | 401 |
| `AlreadyExistsError` | 409 |
| `ModelUnavailableError` | 409 (machine-readable body: `error`, `model_id`, `detail`) |
| `DomainError` (base) | 500 |

`DomainValidationError` is deliberately *not* named `ValidationError` — that name
belongs to Pydantic's parse-time error. `NoInviteError` and `StructuredOutputError`
subclass `DomainError` and are handled at their call sites (see below).

**That table is `STATUS` in `app/exceptions.py`**, and it is the whole translation: `main.py` registers *one* handler, on `DomainError`, because Starlette's handler lookup walks the exception's MRO. Adding an exception means adding a row — or no row at all, since `status_for` walks the MRO too and a subclass inherits its parent's status. The response body comes from the exception's own `body()`; override it only when a client must branch on the failure programmatically (`ModelUnavailableError` is the one case).

A second handler, on `ExceptionGroup`, exists so a domain exception raised under an anyio task group (the MCP transport, the toolset gather) keeps the status it chose: it re-dispatches a `DomainError` leaf via `root_cause()` and **re-raises everything else**. Register it on `ExceptionGroup`, never `BaseExceptionGroup` — the latter is not an `Exception` subclass and Starlette asserts on that while building the middleware stack, i.e. on the first request, not at import.

Routers don't catch or re-raise these — the only router-level `try/except` is for cases that need non-standard handling (e.g. OAuth callback catching `NoInviteError` to emit a 302 redirect instead of a 400).

Use `BaseService.get_or_404(id)` instead of hand-rolling `if not x: raise NotFoundError(...)`.

### SQLAlchemy queries

Always wrap statements in a `stmt` variable before executing — it keeps call sites readable and lets you log/inspect the query during debugging:

```python
# BAD
result = await self.db.execute(
    select(AgentMCPServerDB).where(
        AgentMCPServerDB.agent_id == agent_id,
        AgentMCPServerDB.mcp_server_id == server_id,
    )
)

# GOOD
stmt = select(AgentMCPServerDB).where(
    AgentMCPServerDB.agent_id == agent_id,
    AgentMCPServerDB.mcp_server_id == server_id,
)
result = await self.db.execute(stmt)
```

### FastAPI auth dependencies

Use the shared helpers in `app/auth/dependencies.py`:

- `get_current_user` — required auth (JWT cookie or PAT/JWT bearer)
- `get_current_user_optional` — optional auth (returns `None` if unauthenticated)
- `require_editor` / `require_admin` — role gates

When a role gate's return value is not used in the handler (the dependency runs for its side-effect check only), bind it to `_` to satisfy `ARG001`:

```python
async def create_user(
    user: UserCreate,
    _: UserDB = Depends(require_admin),  # side-effect auth check
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.create_user(user)
```

## Repository Structure

```
auxilia/
├── backend/                           # FastAPI Python application
│   ├── app/
│   │   ├── agents/                    # Agent management & LangGraph runtime
│   │   │   ├── core/                  # AgentService + repository (CRUD, permissions)
│   │   │   ├── mcp_servers/           # AgentMCPServerService (agent↔MCP bindings, tool sync)
│   │   │   ├── subagents/             # SubagentService (supervisor/subagent links)
│   │   │   ├── runs/                  # Durable run runtime — Redis-backed runs, queue, worker, reaper (see runs/SPEC.md)
│   │   │   ├── runtime.py             # Agent runtime — Agent.build / .stream / .invoke (LangGraph)
│   │   │   ├── stream.py              # AI SDK SSE & Slack stream adapters
│   │   │   ├── toolset.py             # Tool binding for the agent
│   │   │   ├── tool_errors.py         # ToolException middleware
│   │   │   ├── router.py              # /agents endpoints (unified)
│   │   │   ├── models.py              # AgentDB, AgentMCPServerDB, permissions, subagent links
│   │   │   └── schemas.py
│   │   ├── auth/                      # JWT + OAuth authentication
│   │   │   ├── tokens/                # Personal access tokens (PAT) service
│   │   │   ├── dependencies.py        # get_current_user, require_admin, require_editor
│   │   │   ├── router.py              # Thin auth endpoints (signin, setup, Google OAuth)
│   │   │   ├── service.py             # AuthService (signup/signin/invite/Google link-or-create)
│   │   │   └── utils.py               # Password hash, JWT encode/decode
│   │   ├── integrations/
│   │   │   ├── langfuse/              # LLM monitoring callback
│   │   │   └── slack/                 # Slack events, commands, interactions
│   │   ├── invites/                   # Admin invites (email → pending role)
│   │   ├── mcp/                       # MCP server management & client
│   │   │   ├── apps/                  # MCP-app UI endpoints (read resource / call tool)
│   │   │   ├── client/                # MCP client, OAuth provider, Redis storage, connectivity probes
│   │   │   ├── servers/               # MCP server CRUD, API-key/OAuth credentials encryption
│   │   │   │                          # catalog.py — official servers from a CDN YAML (see app/utils/remote_catalog.py)
│   │   │   └── router.py              # auxilia_mcp (FastMCP) endpoint — advertises no tools yet
│   │   ├── model_providers/           # LLM provider configuration & catalog
│   │   ├── sandbox/                   # Sandboxed code execution
│   │   ├── threads/                   # Chat thread management
│   │   │   ├── serialization.py       # LangGraph checkpoint → UI message conversion
│   │   │   └── router.py              # Thread CRUD, history & subagent state (runs live in agents/runs/)
│   │   ├── triggers/                  # Scheduled agent runs
│   │   │   ├── scanner.py             # TriggerScanner — due-trigger loop (sibling of runs/reaper)
│   │   │   ├── schedule.py            # Pure cron/timezone math (croniter): validation, next_run_at
│   │   │   ├── service.py             # TriggerService — CRUD + claim_and_enqueue (scanner entrypoint)
│   │   │   └── router.py              # /triggers CRUD + /triggers/schedule/preview
│   │   ├── users/                     # User management
│   │   ├── utils/                     # remote_catalog.py — CDN-hosted catalogs; encryption.py — AES-GCM at rest
│   │   ├── background.py              # PeriodicLoop + LoopHealth registry — supervised
│   │   │                              # background loops; /health reports their liveness
│   │   ├── database.py                # Async engine + request-scoped get_db
│   │   ├── redis_client.py            # Shared async Redis client (durable runtime, out-of-request)
│   │   ├── exceptions.py              # DomainError hierarchy + root_cause() ExceptionGroup unwrap
│   │   ├── main.py                    # FastAPI app + global exception handlers
│   │   ├── models.py                  # BaseDBModel, UUIDMixin, TimestampMixin, AI SDK Message
│   │   ├── repository.py              # BaseRepository[T] — generic CRUD
│   │   ├── service.py                 # BaseService[M, R] — get_or_404 + shared helpers
│   │   └── settings.py                # App-wide settings (pydantic-settings)
│   ├── alembic/                       # Database migrations
│   ├── scripts/                       # One-off utilities — gitignored, not in the repo
│   ├── tests/                         # Pytest test suite (mirrors app/ layout)
│   ├── pyproject.toml                 # Python dependencies (uv) + ruff / mypy / pytest config
│   └── Dockerfile
├── web/                               # Next.js frontend (App Router)
│   ├── src/
│   │   ├── app/
│   │   │   ├── (protected)/           # Authenticated routes (agents, MCP servers)
│   │   │   ├── auth/                  # Signin/signup pages
│   │   │   └── api/                   # API routes (auth, backend proxy)
│   │   ├── components/
│   │   │   ├── ai-elements/           # Chat UI components
│   │   │   ├── layout/                # Sidebar, navigation
│   │   │   ├── providers/             # Context providers
│   │   │   └── ui/                    # shadcn/ui components
│   │   ├── hooks/                     # Custom React hooks
│   │   ├── lib/api/                   # Axios client with case conversion
│   │   ├── stores/                    # Zustand state stores
│   │   └── types/                     # TypeScript type definitions
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml                 # Production setup
├── docker-compose.dev.yml             # Dev services (postgres, redis)
└── Makefile                           # Development commands
```

## Development Commands

### Full Development

```sh
make dev              # Start everything (postgres, redis, backend, frontend) in parallel
```

### Individual Services

```sh
make dev-stack        # Start Docker services (PostgreSQL, Redis)
make dev-backend      # Run migrations + start uvicorn with reload
make dev-frontend     # Start Next.js dev server
```

### Database

```sh
cd backend && uv run alembic upgrade head     # Run migrations
cd backend && uv run alembic revision --autogenerate -m "description"  # Create migration
```

### Docker

```sh
make build            # Build Docker images
make rebuild          # Build without cache
make up               # Start production containers
make down             # Stop containers
make reset            # Stop and remove all volumes
```

### Testing

```sh
cd backend && uv run pytest                                    # Run all tests
cd backend && uv run pytest tests/agents/                      # Run specific module
cd backend && uv run pytest tests/agents/test_router.py -k "test_name"  # Run specific test
```

### Linting

```sh
cd backend && uv run ruff check .         # Lint Python code
cd backend && uv run ruff format .        # Format Python code
```

## Commits & Releases (release-please)

Releases are automated by the **release-please** GitHub Action (`.github/workflows/release-please.yml`), which parses commit messages on `main` — so **every commit that lands on `main` must follow [Conventional Commits](https://www.conventionalcommits.org/)**. PRs are squash-merged: **the PR title becomes the commit on `main`**, so the PR title itself must be conventional (e.g. `feat(triggers): scheduled agent runs`). A non-conventional title means the change never appears in a changelog or version bump.

- Format: `<type>(<optional scope>): <description>`. Common types: `feat`, `fix`, `perf`, `refactor`, `deps`, `revert` (all appear in the changelog); `docs`, `chore`, `test`, `style`, `build`, `ci` (hidden, no bump).
- Monorepo manifest mode (`release-please-config.json`): two packages, `backend` (python) and `web` (node), versioned independently. Which package bumps is decided by the **file paths** the commit touches, not the scope — the scope is changelog cosmetics.
- Pre-1.0 bump rules are active (`bump-minor-pre-major` + `bump-patch-for-minor-pre-major`): `feat`/`fix` bump the **patch**, breaking changes (`feat!:` or a `BREAKING CHANGE:` footer) bump the **minor**.
- On merge, release-please maintains a release PR (`chore: release main`); merging that PR tags the release and triggers the Docker image publish for whichever package was bumped.

## Technology Stack

### Backend (`/backend/`)

- **Framework**: FastAPI (async)
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Database**: PostgreSQL 17
- **Cache**: Redis 7
- **Migrations**: Alembic
- **LLM Orchestration**: LangChain + LangGraph
- **MCP**: MCP SDK + langchain-mcp-adapters
- **Auth**: JWT (HttpOnly cookies) + Google OAuth (Authlib)
- **Password Hashing**: Argon2 (pwdlib)
- **Package Manager**: uv
- **Linter/Formatter**: Ruff
- **Testing**: pytest + pytest-asyncio

### Frontend (`/web/`)

- **Framework**: Next.js 16 (App Router)
- **UI**: React 19, Tailwind CSS 4, shadcn/ui (Radix UI)
- **State**: Zustand
- **AI Streaming**: Vercel AI SDK (`@ai-sdk/react`)
- **HTTP**: Axios (with automatic snake_case/camelCase conversion)
- **Backend Proxy**: All client-side API calls go through a Next.js catch-all route (`/api/backend/[...path]`) that proxies requests to the FastAPI backend (`BACKEND_URL`, defaults to `http://localhost:8000`). This avoids CORS issues and keeps the backend URL private from the browser.

### Supported LLM Providers

- OpenAI (GPT-4o, GPT-4o-mini)
- Anthropic (Claude Haiku, Sonnet, Opus)
- Deepseek (chat, reasoner)
- Google (Gemini Flash, Pro)

## Development Guidelines

### Backend Patterns

See **Backend conventions** above for the full layered architecture, naming rules, transaction model, and exception-handling contract. Additional rules of thumb:

- **Async everywhere**: all database operations, HTTP calls, and MCP interactions use `async/await`
- **Dependency injection**: use FastAPI `Depends()` for database sessions (`get_db`) and auth (`get_current_user` / `require_admin` / `require_editor`)
- **Pure helpers stay out of services**: if a function doesn't need the DB, don't put it on the service. Connectivity probes live in `app/mcp/client/connectivity.py`, not on `MCPServerService`, so callers never have to pass `None` for an unused session.
- **Cross-module service use**: a service can compose another service directly (e.g. `AgentService` constructs a `SubagentService` in its `__init__`). Avoid reaching into another module's repository from a router.

### Frontend Patterns

- **App Router** (not Pages Router)
- **Zustand stores** for client state (agents, threads, MCP servers, user)
- **Axios interceptors** handle camelCase ↔ snake_case conversion automatically; the `tools` JSONB field is preserved as-is
- **shadcn/ui** components in `components/ui/`; feature-specific components live next to their page
- **Never pass an async/Promise-returning function directly to a void event handler** (`onClick`, `onChange`, `onSubmit`, etc.) — ESLint's `@typescript-eslint/no-misused-promises` flags it. Wrap the call so the handler returns void:

  ```tsx
  // BAD
  <button onClick={handleRestore}>      // handleRestore is async
  <button onClick={() => handleSave()}> // also flagged: arrow returns the Promise

  // GOOD
  <button onClick={() => { void handleRestore(); }}>
  ```

  The same rule flags any arrow with an implicit non-void return in a void slot, so prefer a block body (`onClick={() => { setView(tab.key); }}`) over an expression body when the call's return value isn't `void`.

### Agent Permissions

Workspace role levels (`WorkspaceRole`): `member`, `editor`, `admin`. A grant row (`AgentUserPermissionDB`) holds a `PermissionLevel`: `member`, `editor`, `admin`. What a *resolved* check deals in is `EffectivePermission` — the same three plus `owner`, derived from `AgentDB.owner_id` — ordered weakest → strongest. Membership can also be team-derived (`AgentTeamDB`), which resolves to `member`.

`AgentService._resolve_permission` is the resolution, in precedence order:

1. Owner of the agent → `owner`
2. Workspace admin → `admin`
3. Explicit grant in `AgentUserPermissionDB` → `member` / `editor` / `admin`
4. Membership of a team bound to the agent (`AgentTeamDB`) → `member`
5. Otherwise → `None`

It feeds two callers. Reads (`list` / `get`) stamp it onto `AgentResponse.current_user_permission`. **Checks go through `AgentService.require_permission(agent_id, at_least=…, action=…)`** — the single gate, which costs one narrow query (`AgentRepository.get_access`), raises `NotFoundError` for an agent the caller cannot see and `PermissionDeniedError` when their level is too weak. Compare levels with `EffectivePermission.covers(at_least)`, never with `<`/`>`: it is a `str` enum, so the operators compare alphabetically.

Never hand-type a tuple of level strings. Routes whose handler does not otherwise call `AgentService` declare the gate instead: `dependencies=[Depends(require_agent_permission(EffectivePermission.editor, action="…"))]` (`app/agents/dependencies.py`). Both paths end in `require_permission`.

Current gates: edit / config save / MCP bindings / sync-tools / team bindings → `editor`; delete, restore, permanent delete, permission grants, cross-user thread lists → `admin` (owner covers it); `is-ready` → `member`.

The service does **not** filter unauthorized agents out of `list`. Callers (e.g. Slack handlers) must filter on `current_user_permission is not None` when enforcing access.

### MCP Server Security

- API keys are encrypted at rest with AES-GCM (`app/utils/encryption.py`)
- OAuth tokens are stored per-user via `TokenStorageFactory`
- Only remote (streamable HTTP) MCP servers are supported
- **One auth dispatch**: `resolve_transport_auth(server, user_id, repository)` in `app/mcp/client/connectivity.py` turns an `MCPAuthType` into transport credentials, for both the client config the runtime builds and the raw handshake. Adding a scheme is one `match` arm; an unknown one raises on both paths rather than connecting unauthenticated.
- **Per-provider OAuth deviations go in `OAUTH_QUIRKS`** (`app/mcp/client/auth.py`), matched on the issuer, the server URL, or either — never as a new inline `if url == …`.
- **"Needs authorization" is caught at the MCP seam, never globally.** `OAuthAuthorizationRequired` can arrive wrapped in an `ExceptionGroup` (the implicit 401 fires inside the transport's anyio task group), so `connectivity._open_session` and `Toolset.open` unwrap it with `as_oauth_required()` and re-raise the leaf; callers then use a plain `except`. Only endpoints whose job is connecting turn it into a response — `list-tools` returns an `auth_required` variant (a 200), the run and MCP-app endpoints answer 401 explicitly. `main.py` has no handler for it and none for `ExceptionGroup`; don't add one.

### Slack Integration

- Events endpoint: `POST /integrations/slack/events`
- Interactions endpoint: `POST /integrations/slack/interactions`
- Agent selection uses Block Kit buttons
- Tool approvals use approve/reject buttons in threads
- `resolve_user()` maps Slack users to internal users via email lookup

## Environment Setup

- **Python**: 3.11+ (via uv)
- **Node.js**: 20+ (see Dockerfile)
- **Infrastructure**: Docker for PostgreSQL and Redis (`docker-compose.dev.yml`)
- **Environment**: Copy `.env.example` to `.env`

<!-- rtk-instructions v2 -->

# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:

```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)

```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)

```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)

```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)

```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)

```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)

```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)

```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)

```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)

```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands

```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category         | Commands                       | Typical Savings |
| ---------------- | ------------------------------ | --------------- |
| Tests            | vitest, playwright, cargo test | 90-99%          |
| Build            | next, tsc, lint, prettier      | 70-87%          |
| Git              | status, log, diff, add, commit | 59-80%          |
| GitHub           | gh pr, gh run, gh issue        | 26-87%          |
| Package Managers | pnpm, npm, npx                 | 70-90%          |
| Files            | ls, read, grep, find           | 60-75%          |
| Infrastructure   | docker, kubectl                | 85%             |
| Network          | curl, wget                     | 65-70%          |

Overall average: **60-90% token reduction** on common development operations.

<!-- /rtk-instructions -->
