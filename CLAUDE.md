# CLAUDE.md

## Project Overview

auxilia is an open-source web MCP client, designed for users and companies to host and configure their MCP-powered AI assistants. auxilia only supports remote MCP servers. The key idea is that all context is provided to LLMs through MCP (skills, semantic search, web search, etc.), keeping auxilia as simple as possible.

Core features are MCP and agent management:

- **MCP**: workspace admin users can add MCP servers to workspace. Workspace MCP servers are then available to all users, to be bound to any workspace agent.
- **Agent**: an agent is defined by instructions and MCP tools. Tools can be individually configured to be disabled or to require user approval (Human-In-The-Loop).

External integrations:

- **Slack**: invoke workspace agents from Slack.
- **Langfuse**: monitor costs, LLM generations and tool calls.

## Repository Structure

```
auxilia/
├── backend/                      # FastAPI Python application
│   ├── app/
│   │   ├── agents/               # Agent management & LangGraph runtime
│   │   │   ├── hitl.py           # HITL approval extraction from UI messages
│   │   │   ├── stream.py         # AI SDK SSE & Slack stream adapters
│   │   │   └── runtime.py        # Agent invocation & tool orchestration
│   │   ├── auth/                 # JWT + OAuth authentication
│   │   ├── integrations/
│   │   │   ├── langfuse/         # LLM monitoring callback
│   │   │   └── slack/            # Slack events, commands, interactions
│   │   ├── mcp/                  # MCP server management & client
│   │   │   ├── client/           # MCP client, OAuth, token storage
│   │   │   └── servers/          # MCP server CRUD, encryption
│   │   ├── model_providers/      # LLM provider configuration
│   │   ├── threads/              # Chat thread management
│   │   │   ├── serialization.py  # LangGraph checkpoint → UI message conversion
│   │   │   └── router.py         # Thread CRUD & history endpoints
│   │   ├── users/                # User management
│   │   ├── database.py           # SQLAlchemy async engine
│   │   └── main.py               # FastAPI app entrypoint
│   ├── alembic/                  # Database migrations
│   ├── tests/                    # Pytest test suite
│   ├── pyproject.toml            # Python dependencies (uv)
│   └── Dockerfile
├── web/                          # Next.js frontend (App Router)
│   ├── src/
│   │   ├── app/
│   │   │   ├── (protected)/      # Authenticated routes (agents, MCP servers)
│   │   │   ├── auth/             # Signin/signup pages
│   │   │   └── api/              # API routes (auth, backend proxy)
│   │   ├── components/
│   │   │   ├── ai-elements/      # Chat UI components
│   │   │   ├── layout/           # Sidebar, navigation
│   │   │   ├── providers/        # Context providers
│   │   │   └── ui/               # shadcn/ui components
│   │   ├── hooks/                # Custom React hooks
│   │   ├── lib/api/              # Axios client with case conversion
│   │   ├── stores/               # Zustand state stores
│   │   └── types/                # TypeScript type definitions
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml            # Production setup
├── docker-compose.dev.yml        # Dev services (postgres, redis)
└── Makefile                      # Development commands
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

- **Router → Service/Utils → Models**: each module has `router.py` (endpoints), `utils.py` or `service.py` (business logic), and `models.py` (DB + Pydantic schemas)
- **Model naming**: `*DB` for database models, `*Create`/`*Update`/`*Read` for request/response schemas
- **Async everywhere**: all database operations, HTTP calls, and MCP interactions use `async/await`
- **Dependency injection**: use FastAPI `Depends()` for database sessions (`get_db`) and auth (`get_current_user`)

### Frontend Patterns

- **App Router** (not Pages Router)
- **Zustand stores** for client state (agents, threads, MCP servers, user)
- **Axios interceptors** handle camelCase ↔ snake_case conversion automatically; the `tools` JSONB field is preserved as-is
- **shadcn/ui** components in `components/ui/`; feature-specific components live next to their page

### Agent Permissions

Agents have a permission system with levels: `owner`, `admin`, `editor`, `user`. The `read_agents()` utility attaches `current_user_permission` to each agent but does not filter — callers must filter agents where `current_user_permission is not None` to enforce access control.

### MCP Server Security

- API keys are encrypted at rest with AES-GCM (`app/mcp/servers/encryption.py`)
- OAuth tokens are stored per-user via `TokenStorageFactory`
- Only remote (streamable HTTP) MCP servers are supported

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

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->