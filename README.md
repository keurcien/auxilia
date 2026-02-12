# auxilia

A lightweight web MCP client designed to host your MCP-powered AI assistants. auxilia is designed to only support remote MCP servers.

Built with langgraph and the AI SDK.

## 🚀 Quick Start

1. **Clone the repository:**

```bash
git clone https://github.com/keurcien/auxilia.git
cd auxilia
```

2. **Configure Environment:**

Copy `.env.example` to `.env` and add your LLM API keys (OpenAI, Anthropic, etc.).

3. **Start services:**

Run `make build && make up` in a terminal to start the Docker containers.

4. **Access interface**:

Open http://localhost:3000 in your browser.

## 🚧 Development

2. **Configure Environment:**

Copy `.env.example` to `.env.dev` and add your LLM API keys (OpenAI, Anthropic, etc.).

3. **Start services:**

Run `npm install` in web folder.
Run `make dev` in a terminal.

## Google Sign In

To set up Google Sign In, add your Google client credentials to the `.env` file.
