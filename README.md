<div align="center">
  <img src="docs/public/logo.svg#gh-light-mode-only" alt="auxilia" height="72" />
  <img src="docs/public/logo-dark.svg#gh-dark-mode-only" alt="auxilia" height="72" />

  <h1>auxilia</h1>
  <h3>The open-source web MCP client for teams.</h3>

  <p>
    Host AI assistants backed by remote <a href="https://modelcontextprotocol.io/">Model Context Protocol</a> servers,
    share them across your organization, and keep every integration — tools, credentials, observability — on your own infrastructure.
  </p>

  <p>
    <a href="https://github.com/keurcien/auxilia/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/keurcien/auxilia?color=blue"></a>
    <a href="https://github.com/keurcien/auxilia/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/keurcien/auxilia?style=flat"></a>
    <a href="https://github.com/keurcien/auxilia/issues"><img alt="Issues" src="https://img.shields.io/github/issues/keurcien/auxilia"></a>
    <a href="https://github.com/keurcien/auxilia/pulls"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
    <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
    <img alt="Node" src="https://img.shields.io/badge/node-20%2B-339933">
  </p>

  <p>
    <a href="#-quick-start"><b>Quick start</b></a> ·
    <a href="#-features"><b>Features</b></a> ·
    <a href="#-architecture"><b>Architecture</b></a> ·
    <a href="#-integrations"><b>Integrations</b></a> ·
    <a href="#-documentation"><b>Docs</b></a>
  </p>
</div>

---

https://github.com/user-attachments/assets/3236f9da-28c5-44c8-8c2c-4c68199f187c

## Why auxilia

Most MCP clients today are desktop apps tied to a single user. **auxilia** is different:

- 🌐 **Web-based** — accessible from any browser, no desktop app to install
- 👥 **Multi-user** — admins register MCP servers once; every teammate can bind them to agents
- 🔌 **Remote MCP only** — built for server-to-server Streamable HTTP connections, not local stdio
- 🏠 **Self-hosted** — runs on your infrastructure; credentials and conversation data stay in your database
- 🧩 **MCP-native** — tools, skills, and resources all flow through MCP, keeping the core tiny

Learn more about auxilia: https://auxilia-docs.vercel.app/

## ✨ Features

### 🤖 Agents

- Define agents with a **system prompt**, **avatar** (emoji + color) and bound MCP servers
- **Subagents** — coordinator agents can dispatch work to specialized subagents
- **Workspace roles & per-agent permissions** — `owner`, `admin`, `editor`, `user`, plus private/shared agents
- **Streaming responses** over SSE via the LangGraph SDK, with full LangGraph checkpointing

### 🔧 Tools & MCP Servers

- Register **remote MCP servers** at the workspace level — everyone can reuse them
- Per-tool control: **always allow**, **needs approval**, or **disabled**
- **Human-in-the-loop approvals** inline in chat or Slack
- **AES-GCM encryption** for API keys at rest, per-user **OAuth 2.1** token storage in Redis
- Built-in **connectivity probes** with automatic token refresh

### 🧪 Code Sandbox

Turn any agent into a lightweight data-analyst with an **isolated Linux environment** powered by [OpenSandbox](https://github.com/alibaba/opensandbox):

- Filesystem tools: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Shell access via `execute`
- Lazy-spawned containers with a 30-minute TTL, reconnectable across browser refreshes

⚠️ To enable code execution, you first need to deploy Opensandbox (either on a simple VM or Kubernetes), and set it up in auxilia.

### 💬 Slack Integration

- Start a chat with auxilia and pick an agent
- Tool-approval buttons rendered with Block Kit
- Slack ↔ auxilia users matched by email

### 📊 Observability

- **Langfuse** integration — trace every LLM call, tool call, and cost per agent and user
- Request-scoped profiling via `RequestTimer` (see `app/utils/timer.py`)

### 🔐 Authentication

- JWT sessions over HttpOnly cookies
- **Google OAuth** sign-in (Authlib)
- **Personal Access Tokens** (PATs) for programmatic access
- Argon2 password hashing

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- At least one LLM API key (Anthropic, OpenAI, Google, or DeepSeek)

### Run with Docker

```bash
git clone https://github.com/keurcien/auxilia.git
cd auxilia
cp .env.example .env   # add your LLM API keys
make build && make up
```

Open [http://localhost:3000](http://localhost:3000). The first account you create becomes the workspace **admin**.

### Run for development

```bash
cp .env.example .env
make dev
```

`make dev` starts PostgreSQL, Redis, the FastAPI backend (with migrations applied) and the Next.js frontend in parallel — all with hot reload.

See the [Get Started guide](https://auxilia-docs.vercel.app/get-started) for the full walkthrough.

## 🤝 Integrations

### LLM Providers

| Provider  | Models                                       |
| --------- | -------------------------------------------- |
| Anthropic | Claude Haiku 4.5, Sonnet 4.6, Opus 4.6       |
| OpenAI    | GPT-4o-mini                                  |
| Google    | Gemini 3 Flash Preview, Gemini 3 Pro Preview |
| DeepSeek  | DeepSeek Chat, DeepSeek Reasoner             |

### MCP Servers — one-click install

Notion · Linear · GitHub · HubSpot · BigQuery · Slack · Sentry

Plus any custom remote MCP server — just paste a URL and your OAuth credentials or API keys.

### Workspace integrations

- **Slack** — invoke agents, approve tools, stream replies in threads
- **Langfuse** — LLM + tool-call tracing and cost attribution
- **Google OAuth** — SSO for your workspace

## 💡 What you can build

- A **CRM agent** that queries HubSpot and drafts Slack replies
- A **data analyst** that runs BigQuery and stores the analysis in a Notion document
- An **on-call assistant** that reads Sentry issues, searches Linear, and opens PRs via GitHub
- A **workspace coordinator** that dispatches work to specialized subagents

## 📚 Documentation

- [Get Started](https://auxilia-docs.vercel.app/get-started) — run auxilia locally
- [Agents](https://auxilia-docs.vercel.app/agents) — configuration, permissions, subagents
- [MCP Servers](https://auxilia-docs.vercel.app/mcp-servers) — registration, auth, examples
- [Tools](https://auxilia-docs.vercel.app/tools) — per-tool approval rules
- [Sandbox](https://auxilia-docs.vercel.app/sandbox) — enable code execution for an agent
- [Deployment](https://auxilia-docs.vercel.app/deployment) — Docker Compose, Google Cloud Run
- [Integrations](https://auxilia-docs.vercel.app/integrations) — Slack, Langfuse


## 🗺 Roadmap

- [ ] Scheduled tasks
- [ ] Skills
- [ ] Support for more sandboxes (e.g. Daytona) 
- [ ] Deployment guides
- [ ] More SSO providers (Okta, Entra ID)

Have an idea? [Open an issue](https://github.com/keurcien/auxilia/issues/new) or start a discussion.

## 🤝 Contributing

Contributions are very welcome! Whether it's a bug report, an agent idea, a new MCP server recipe, or a UI improvement:

1. Fork the repo and create a branch (`git checkout -b feature/my-change`)
2. Run `make dev` and make sure tests pass (`cd backend && uv run pytest`)
3. Open a pull request

Please read `CLAUDE.md` in the root of the repo — it documents the backend's layered architecture (router → service → repository → model) and naming conventions.

## 📄 License

[AGPL-3.0](./LICENSE) — free to use, modify, and self-host.

---

<div align="center">
  <sub>Built with ❤️ using <a href="https://www.langchain.com/langgraph">LangGraph</a> and the <a href="https://modelcontextprotocol.io/">Model Context Protocol</a>.</sub>
</div>
