<div align="center">
  <img src="docs/public/logo.svg#gh-light-mode-only" alt="auxilia" width="112" />
  <img src="docs/public/logo-dark.svg#gh-dark-mode-only" alt="auxilia" width="112" />

  <h1>auxilia</h1>
  <p><strong>A self-hosted home for team AI agents.</strong></p>
  <p>
    Build once, then use your agents from the browser, an installable mobile app,
    Slack, Telegram, WhatsApp, webhooks, or your own products.
  </p>

  <p>
    <a href="https://github.com/jr-k/auxilia/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/jr-k/auxilia?display_name=tag&sort=semver"></a>
    <a href="https://github.com/jr-k/auxilia/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/jr-k/auxilia"></a>
    <a href="https://github.com/jr-k/auxilia/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/jr-k/auxilia?style=flat"></a>
    <a href="https://github.com/jr-k/auxilia/pkgs/container/auxilia-web"><img alt="Container images" src="https://img.shields.io/badge/images-GHCR-181717?logo=github"></a>
    <a href="./LICENSE"><img alt="AGPL-3.0 license" src="https://img.shields.io/github/license/jr-k/auxilia"></a>
  </p>

  <p>
    <a href="#quick-start"><strong>Quick start</strong></a>
    &nbsp;/&nbsp;
    <a href="#what-this-fork-adds"><strong>Fork additions</strong></a>
    &nbsp;/&nbsp;
    <a href="#the-agent-platform-underneath"><strong>Platform</strong></a>
    &nbsp;/&nbsp;
    <a href="https://auxilia-docs.vercel.app/"><strong>Documentation</strong></a>
  </p>
</div>

---

auxilia gives a team one place to create, run, share, and govern AI agents. Connect
remote MCP servers, choose an LLM, add skills and context, then let people use the
result without asking everyone to configure their own stack.

It is open source, self-hosted, and provider-independent. Conversations,
credentials, permissions, and usage data stay in infrastructure you control.

## Why this fork

This repository builds on the
[original auxilia project](https://github.com/keurcien/auxilia) and focuses on
the parts that turn an agent playground into a product people can use every day:
mobile access, notifications, projects, collaboration, administration,
integrations, and operational resilience.

The fork follows a short release cycle. Features proven in real deployments are
shipped in small increments, then hardened as usage grows.

## What this fork adds

The highlights below focus on capabilities added by this fork.

### Use auxilia anywhere

- **Installable PWA**: add auxilia to iOS, Android, or desktop with instance
  branding, app icons, and a standalone experience.
- **Web Push notifications**: receive agent completion alerts outside the app,
  open the right conversation directly, and customize the Android monochrome
  notification badge.
- **Mobile-native navigation**: responsive chat and administration views,
  touch-driven drawers that follow the finger, safe-area support, and layouts
  designed for narrow screens.
- **Personal preferences**: browser notifications, response sounds, external
  link confirmation, navigation shortcuts, and a guided preferences onboarding.

### Keep work and context together

- **Projects**: group conversations and triggers in nested folders, attach
  project instructions and context files, control visibility, and manage
  projects through MCP.
- **Better conversations**: queue prompts while a run is active, track unread
  replies, filter and organize threads, manage conversation resources, and
  preserve work across long-running jobs.
- **Memories**: let agents retain useful user context automatically, with
  controls for reviewing and managing what was remembered.
- **Artifacts and sharing**: persist generated files locally or in object
  storage, preview common formats, download results, and publish rich,
  read-only conversation snapshots.

### Connect agents to the rest of the company

- **Side channels**: assign agents to Slack, Telegram, and WhatsApp. Conversations
  keep their runtime settings, tool approvals, context, and progress updates.
- **Managed databases**: connect PostgreSQL, MySQL, MariaDB, SQL Server, and
  Oracle, or upload SQLite files. Credentials are encrypted, writes can be
  disabled, and query limits stay under workspace control.
- **Automation**: trigger agents on a schedule or through a webhook, override
  selected run inputs, and follow execution in the same durable runtime as web
  conversations. One-shot triggers pause themselves after their first firing,
  for reminders that must not repeat.
- **Native data access**: add Gmail and provider-native web search alongside
  remote MCP tools.

### Run a real multi-user instance

- **Multiple workspaces**: isolate members, agents, projects, MCP servers,
  integrations, and credentials while keeping workspace switching simple.
- **Teams and permissions**: combine workspace roles, teams, resource
  visibility, and per-agent grants for precise access control.
- **Administration**: supervise user sessions, inspect usage and costs, manage
  conversations, configure integrations, and propagate workspace changes in
  real time.
- **Security and identity**: password recovery, TOTP two-factor authentication,
  Google sign-in, personal access tokens, encrypted secrets, and configurable
  authentication policies.
- **White-label appearance**: change the instance name, logos, PWA identity,
  browser metadata, notification badge, and authentication branding from the
  application.

### Operate MCP and models without the rough edges

- **Expanded MCP management**: a large remote-server catalog, richer connection
  diagnostics, manual OAuth flows, shared service identities, custom
  credentials, provider quirks, and per-tool controls.
- **auxilia as an MCP server**: expose authenticated workspace operations to
  other MCP clients through OAuth.
- **More model choice**: configure Anthropic, OpenAI, Google, DeepSeek,
  OpenRouter, Ollama, Xiaomi, and Meta models from the administration UI.
- **Graceful degradation**: a broken sandbox, unavailable MCP server, skill
  failure, or subagent issue is surfaced as a warning without blocking a prompt
  that the LLM can still answer.

## The agent platform underneath

The original auxilia foundations remain at the center of the product:

- reusable agents with instructions, models, and individually governed tools
- remote MCP servers with API key, OAuth, and service authentication
- human approval before sensitive tool calls
- skills, subagents, structured output, and sandboxed code execution
- durable background runs with streaming, resume, cancellation, and recovery
- scheduled triggers and an API for embedding agents in other products
- Langfuse observability and detailed usage accounting

## Quick start

You need Docker and Docker Compose.

```bash
git clone https://github.com/jr-k/auxilia.git
cd auxilia
cp .env.example .env
make build
make up
```

Open [http://localhost:3000](http://localhost:3000). The first account becomes
the administrator. Add an LLM provider in the settings, create an agent, and
start a conversation.

PostgreSQL, Redis, the optional database gateway, and the local sandbox service
are included in the Compose stack.

### Before a production deployment

At minimum, replace these development values in `.env`:

```dotenv
BACKEND_JWT_SECRET_KEY=replace-with-a-long-random-secret
BACKEND_ENCRYPTION_SALT=replace-with-a-stable-random-secret
BACKEND_COOKIE_SECURE=true
```

Keep `BACKEND_ENCRYPTION_SALT` stable after credentials have been saved. Changing
it without re-encrypting existing data makes those secrets unreadable.

Optional features use their own settings:

- `WEB_PUSH_VAPID_*` for browser and PWA notifications
- `SMTP_*` for password recovery email
- artifact storage variables for S3-compatible storage or Google Cloud Storage
- side-channel credentials for Slack, Telegram, and WhatsApp

See the [deployment documentation](https://auxilia-docs.vercel.app/deploy) for
the complete configuration.

## Development

The local development command starts PostgreSQL, Redis, the backend, and the
frontend with hot reload:

```bash
make dev
```

The main stack is:

- **Frontend**: Next.js 16, React 19, Tailwind CSS, and Zustand
- **Backend**: FastAPI, SQLModel, PostgreSQL, and Redis
- **Agent runtime**: LangGraph, deepagents, and the Agent Streaming Protocol
- **Tools**: remote MCP over Streamable HTTP
- **Sandbox**: OpenSandbox locally, with pluggable hosted providers

Architecture and contribution conventions live in
[`CLAUDE.md`](./CLAUDE.md) and [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Documentation and help

- [Documentation](https://auxilia-docs.vercel.app/)
- [Releases](https://github.com/jr-k/auxilia/releases)
- [Issues](https://github.com/jr-k/auxilia/issues)
- [Original project](https://github.com/keurcien/auxilia)

## License

auxilia is available under the [AGPL-3.0 license](./LICENSE).

<div align="center">
  <sub>
    Built with <a href="https://www.langchain.com/langgraph">LangGraph</a> and
    the <a href="https://modelcontextprotocol.io/">Model Context Protocol</a>.
  </sub>
</div>
