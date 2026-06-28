# auxilia Web

Next.js 16 (App Router) frontend for auxilia — the chat UI, agent and MCP-server
management, and authentication.

## Stack

- **Framework**: Next.js 16 (App Router), React 19
- **UI**: Tailwind CSS 4, shadcn/ui (Radix UI)
- **State**: Zustand
- **AI streaming**: `@langchain/langgraph-sdk` (`useStream`) + Vercel AI SDK
- **HTTP**: Axios with automatic snake_case ↔ camelCase conversion

## Backend proxy

All client-side API calls go through a Next.js catch-all route
(`/api/backend/[...path]`) that proxies to the FastAPI backend (`BACKEND_URL`,
default `http://localhost:8000`). This avoids CORS and keeps the backend URL
private from the browser. The proxy forwards response headers (including
`X-Run-Id`).

## Durable run client

Chat streaming is wired to the backend's durable agent runtime via
`src/hooks/use-durable-run.ts`. A run outlives its HTTP request, so the hook:

- captures the `X-Run-Id` header so **Stop** cancels the run server-side
  (`POST /threads/{thread_id}/runs/{run_id}/cancel`), not just locally;
- **reattaches** to an in-flight run on mount by replaying its event log
  (`GET /threads/{thread_id}/runs/{run_id}/stream`);
- aborts the in-flight fetch on thread switch / unmount.

## Development

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # production build
npm run lint       # ESLint
```

Run the backend separately (see `../backend/README.md`) or the whole stack with
`make dev` from the repo root.
