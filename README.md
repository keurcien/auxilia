<div align="center">
  <img src="docs/public/logo.svg#gh-light-mode-only" alt="auxilia" height="72" />
  <img src="docs/public/logo-dark.svg#gh-dark-mode-only" alt="auxilia" height="72" />

  <h1>auxilia</h1>
  <h3>The open-source, self-hosted web client for MCP-powered AI agents — built for teams.</h3>

  <p>
    <a href="https://github.com/keurcien/auxilia/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/keurcien/auxilia?color=blue"></a>
    <a href="https://github.com/keurcien/auxilia/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/keurcien/auxilia?style=flat"></a>
    <a href="https://github.com/keurcien/auxilia/issues"><img alt="Issues" src="https://img.shields.io/github/issues/keurcien/auxilia"></a>
    <a href="https://github.com/keurcien/auxilia/pulls"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
  </p>

  <p>
    <a href="#-quick-start"><b>Quick start</b></a> ·
    <a href="#-why-auxilia"><b>Why auxilia</b></a> ·
    <a href="#-features"><b>Features</b></a> ·
    <a href="#-integrations"><b>Integrations</b></a> ·
    <a href="https://auxilia-docs.vercel.app/"><b>Docs</b></a>
  </p>
</div>

---

https://github.com/user-attachments/assets/3236f9da-28c5-44c8-8c2c-4c68199f187c

**auxilia is a web platform for running AI agents as a team.** An admin sets up [MCP](https://modelcontextprotocol.io/) servers and agents once, and the whole workspace shares them — no more everyone configuring their own assistant with their own prompts and credentials. Anyone can create an agent and experiment, zero technical skills required: agents chat in the browser or in Slack, use your internal tools, ask a human for approval before sensitive actions, and run on schedules or in the background. An agent is only as good as the environment you give it. That's where auxilia comes in: iterating quickly is how you find what's missing — a tool it needed, a doc that's outdated, data that isn't as clean as you thought. The more gaps you close, the more reliable your agents become; when one proves itself, plug it into your own products through the API. You pick the LLM provider (Anthropic, OpenAI, Google, DeepSeek) and can switch anytime — and because it's self-hosted, conversations, credentials, and usage data never leave your infrastructure.

## 🤔 Why auxilia

Most MCP clients are desktop apps tied to a single user: every teammate reinvents the same agent, alone, in their own tool. auxilia is the middle ground between "everyone has their own ChatGPT tab" and building a custom AI platform:

- 🧪 **A playground for the whole company** — business users build and test agents themselves, no code. Not every experiment is a keeper — that's the point: everyone gets hands-on intuition for what agents can (and can't) do, cheaply.
- 👥 **One place, shared agents** — register MCP servers and agents once; the whole team reuses them, with workspace roles and per-agent permissions.
- 🏠 **Your infra, your data** — self-hosted; conversations, API keys (AES-GCM encrypted at rest) and per-user OAuth tokens stay in your own database and Redis.
- 🔓 **No provider lock-in** — swap Anthropic, OpenAI, Google, or DeepSeek per agent as pricing and quality shift.
- ✅ **Guardrails built in** — each tool can be always-allowed, require human approval (in chat or Slack), or be disabled.
- 🔌 **Remote MCP native** — any remote (Streamable HTTP) MCP server becomes a tool: internal services or one-click Notion, Linear, GitHub, HubSpot, BigQuery, Slack, Sentry.

## 🚀 Quick start

All you need is [Docker](https://docs.docker.com/get-docker/) and **one LLM API key** (Anthropic, OpenAI, Google, or DeepSeek).

```bash
git clone https://github.com/keurcien/auxilia.git
cd auxilia
cp .env.example .env      # paste at least one LLM API key
make build && make up
```

Open **http://localhost:3000** — the first account you create becomes the workspace **admin**. Add an MCP server, create an agent, and start chatting.

PostgreSQL and Redis are started and wired up by Docker Compose; every other setting has a working dev default. The `.env` at a glance:

| Variable(s) | When you need it |
| --- | --- |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `DEEPSEEK_API_KEY` | **At least one.** Each key unlocks that provider's models in the model picker. |
| `SALT`, `JWT_SECRET_KEY`, `COOKIE_SECURE` | **Before production.** Encryption salt for stored MCP API keys, session signing secret, and `COOKIE_SECURE=true` behind HTTPS. Dev defaults work locally. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional — Google OAuth sign-in (SSO). |
| `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` | Optional — chat with agents from Slack. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional — tracing + cost attribution per agent and user. |
| `OPEN_SANDBOX_*` | Optional — isolated code execution for agents. |
| `RUN_*` | Tuning for the background run worker (concurrency, timeouts). Defaults are fine. |

Developing? `make dev` runs PostgreSQL, Redis, the FastAPI backend (migrations applied) and the Next.js frontend in parallel, all with hot reload. Full walkthrough in the [Get Started guide](https://auxilia-docs.vercel.app/get-started).

## ✨ Features

| | |
| --- | --- |
| 🤖 **Agents** | System prompt, avatar, and bound MCP servers per agent. Coordinator agents dispatch work to **subagents**. Streaming responses with full LangGraph checkpointing. |
| 👥 **Team management** | Workspace roles (`member`, `editor`, `admin`), private or shared agents, per-agent permissions and team-based access. |
| 🔧 **Tools & MCP servers** | Register remote MCP servers once at the workspace level. Per-tool rules: **always allow**, **needs approval**, or **disabled**. Connectivity probes with automatic OAuth token refresh. |
| ✅ **Human-in-the-loop** | Approve sensitive tool calls right from the chat — or from Slack, with Block Kit buttons. |
| ⏰ **Scheduled triggers** | Give an agent standing instructions on a cron + timezone schedule ("every weekday at 8am"). Each firing runs in the background as its owner and lands in the thread list like any conversation. |
| ⚙️ **Durable background runs** | Runs are Redis-backed and survive the browser: close the tab mid-answer, reopen the thread, and reattach to the live stream — or cancel it server-side. |
| 🧪 **Code sandbox** | Give an agent an isolated Linux environment via [OpenSandbox](https://github.com/alibaba/opensandbox) — filesystem tools + shell — and turn it into a data analyst. |
| 📊 **Observability** | Langfuse tracing on every LLM and tool call, with cost attribution per agent and per user. |
| 🔐 **Auth & security** | JWT sessions (HttpOnly cookies), Google OAuth SSO, Personal Access Tokens for API access, Argon2 password hashing, AES-GCM encryption of stored API keys, per-user OAuth 2.1 token storage. |

## 🤝 Integrations

**LLM providers**

| Provider | Models |
| --- | --- |
| Anthropic | Claude Haiku 4.5, Sonnet 4.6, Sonnet 5 |
| OpenAI | GPT-4o mini |
| Google | Gemini 3 Flash Preview, Gemini 3 Pro Preview |
| DeepSeek | DeepSeek v4 Flash, v4 Pro |

**MCP servers — one-click install**: Notion · Linear · GitHub · HubSpot · BigQuery · Slack · Sentry — or paste the URL of any custom remote MCP server with its OAuth credentials or API key.

**Workspace tools**: Slack, Langfuse, Google OAuth SSO.

## 💡 From playground to production

A few agents we run ourselves:

**📊 A data analyst that answers with dashboards, not spreadsheets.** Plugged into our BigQuery warehouse, with a custom MCP server that renders interactive charts and dashboards *inside the chat*. "How did sales move after the price change?" used to be a ticket for the data team; now it's a question anyone types and gets answered — with a graph — in seconds.

**🎧 A super agent behind our customer support.** One orchestrator dispatches specialized subagents — orders, refunds, logistics — and delivers ready-to-send suggestions straight into our support tool through the invoke API. It was built and tuned like any other workspace agent, then wired into the product without changing a line of it.

**💶 A pricing analyst that does the work nobody wants twice.** Hand it a spreadsheet with thousands of messy, wildly inconsistent rows, and it writes and runs its own code in an isolated sandbox to clean, cross-check, and price every one of them. The same sandbox trick stretches surprisingly far — we've used it to train and deploy small ML models.

## 📚 Documentation

Full docs at **[auxilia-docs.vercel.app](https://auxilia-docs.vercel.app/)**:

- [Get Started](https://auxilia-docs.vercel.app/get-started) — run auxilia locally
- [Agents](https://auxilia-docs.vercel.app/agents) — configuration, permissions, subagents
- [MCP Servers](https://auxilia-docs.vercel.app/mcp-servers) — registration, auth, examples
- [Tools](https://auxilia-docs.vercel.app/tools) — per-tool approval rules
- [Sandbox](https://auxilia-docs.vercel.app/sandbox) — enable code execution for an agent
- [Deployment](https://auxilia-docs.vercel.app/deployment) — Docker Compose, Google Cloud Run
- [Integrations](https://auxilia-docs.vercel.app/integrations) — Slack, Langfuse

## 🗺 Roadmap

- [x] Scheduled triggers
- [ ] Skills
- [ ] Support for more sandboxes (e.g. Daytona)
- [ ] Deployment guides
- [ ] More SSO providers (Okta, Entra ID)

Have an idea? [Open an issue](https://github.com/keurcien/auxilia/issues/new) or start a discussion.

## 🤝 Contributing

Contributions are very welcome — bug reports, agent ideas, MCP server recipes, UI fixes:

1. Fork the repo and create a branch (`git checkout -b feature/my-change`)
2. Enable the git hooks once per clone: `pre-commit install` — they run ruff on changed Python and a stricter type-aware ESLint config on changed `web/` files
3. Run `make dev` and make sure tests pass (`cd backend && uv run pytest`)
4. Open a pull request — **the PR title must follow [Conventional Commits](https://www.conventionalcommits.org/)** (e.g. `feat: …`, `fix: …`); PRs are squash-merged and release-please derives versions and changelogs from the titles

Please read [`CLAUDE.md`](./CLAUDE.md) first — it documents the backend's layered architecture (router → service → repository → model) and naming conventions.

## 📄 License

[AGPL-3.0](./LICENSE) — free to use, modify, and self-host.

---

<div align="center">
  <sub>Built with ❤️ using <a href="https://www.langchain.com/langgraph">LangGraph</a> and the <a href="https://modelcontextprotocol.io/">Model Context Protocol</a>.</sub>
</div>
