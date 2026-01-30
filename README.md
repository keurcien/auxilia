# auxilia

A lightweight web MCP client designed to host your MCP-powered AI assistants. auxilia is designed to only support remote MCP servers.

Built with langgraph and the AI SDK.

## Quick start

1. Clone the repository
2. Copy the .env.example file and rename it .env
3. Set an LLM provider API key (OpenAI, Anthropic, ...) to the .env file
4. Open a terminal and run `docker compose up --build`

## Development

1. Set an LLM provider API key (OpenAI, Anthropic, ...) to the .env.development file
2. Open a terminal and run `docker compose -f docker-compose.dev.yml up --build`
3. Open a terminal, cd into backend and run `uv run uvicorn app.main:app --reload`
4. Open a terminal, cd into web and run `npm run dev`

## Google Sign In

To set up Google Sign In, add your Google client credentials to the `.env` file.
