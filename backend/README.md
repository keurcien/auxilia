# auxilia Backend

FastAPI backend for the auxilia project with MCP (Model Context Protocol) server integration and OAuth authentication.

## Features

- **MCP Server Integration**: Connect to multiple MCP servers (DeepWiki, Data Gouv, Notion, etc.)
- **OAuth 2.0 Flow**: Web OAuth implementation with Redis-based callback handling
- **Redis Pub/Sub**: Real-time communication for OAuth callbacks
- **LangGraph Integration**: Agent-based conversation management
- **Thread Management**: Persistent conversation threads with checkpointing
- **Durable Agent Runtime**: Redis-backed runs that outlive the HTTP request — reattachable streams, server-side cancel, and orphan recovery, distributed across instances via a shared queue. The `/threads/{thread_id}/runs/*` API (stream, invoke, reattach, cancel) is served by `app/agents/runs/`; see [`app/agents/runs/SPEC.md`](app/agents/runs/SPEC.md).

## Prerequisites

- Python 3.11+
- Redis (via Docker Compose)
- [uv](https://github.com/astral-sh/uv) package manager

## Quick Start

### 1. Start Redis

From the project root:

```bash
docker compose up -d
```

Verify Redis is running:

```bash
docker compose ps
redis-cli ping  # Should return "PONG"
```

### 2. Install Dependencies

```bash
cd backend
uv sync
```

### 3. Run the Backend

```bash
uv run fastapi dev app/main.py
```

The API will be available at `http://localhost:8000`

API documentation: `http://localhost:8000/docs`

## Conversation cost estimates

`GET /threads/{thread_id}/cost` returns a conversation estimate, including
subagents and per-message breakdowns. `GET
/threads/{thread_id}/messages/{message_id}/cost` returns one assistant call
(404 if that assistant message is absent). Both use the same owner/admin read
permissions as the conversation state endpoint. Costs are computed on demand;
these GET routes do not store message costs or change checkpoints.

Add optional `prices` to model entries in the model whitelist (the CDN document
when configured, or `app/model_providers/whitelist.yaml` for the bundled
fallback). Rates are **USD per token**, following Langfuse’s `prices` usage-type
keys; all three are required,
nonnegative finite decimal values. Model picker and management responses expose
this metadata. See [Langfuse’s usage-key conventions](https://github.com/langfuse/langfuse/blob/main/.agents/skills/add-model-price/references/provider-usage-key-matrix.md).
Example rates below are illustrative, not provider prices:

```yaml
prices:
  input: "2e-6"
  input_cache_read: "0.5e-6"
  input_cache_creation: "2.5e-6"  # optional
  output: "8e-6"
```

`input`, `input_cache_read` and `output` are required. `input_cache_creation`
(cache writes) is optional: without it, writes are charged at the `input` rate.

The formula for each assistant call is:

```text
(input_tokens - cache_read - cache_write) * prices.input
 + cache_read * prices.input_cache_read
 + cache_write * prices.input_cache_creation   (or prices.input)
 + output_tokens * prices.output
```

Prices are provider list prices in US dollars, divided by one million. For
example, `"2e-6"` means $2 per million tokens. Like Langfuse, this API reports
costs in USD per token; every amount it returns is in USD.

Usage comes from LangChain's `usage_metadata`; an absent cache detail means
zero. Cache writes are read from `cache_creation` or, depending on the
langchain-anthropic version, from the `ephemeral_5m_input_tokens` /
`ephemeral_1h_input_tokens` split; 1-hour writes are priced like 5-minute ones.
Tiered (long-prompt) rates, tools, storage and other non-token fees are outside
this estimate.

The reader streams retained `messages` task writes once, including messages
removed by context compaction, and counts each assistant message ID once across
root/subagent namespaces. It avoids reconstructing every checkpoint. A recognized response model overrides the thread's pinned
model; otherwise the pinned definition supplies the rate (including when a
provider returns a versioned name for an alias). On-demand estimates use **current** catalog prices, even for disabled models;
editing rates changes the estimate for existing threads.

The conversation response includes `complete`, `total_cost`,
`known_cost`, `call_count`, `unpriced_call_count`, aggregate `usage_details`,
and `messages`. Each message includes `usage_details` and `cost_details`.
The conversation also returns a per-bucket `cost_details` over its priced calls.
Both detail objects use `input`, `input_cache_read`, `input_cache_creation`,
`output`, and `total`. `usage_details.input` excludes cache reads and writes, so
its four buckets sum to `total`.
Decimal amounts serialize as JSON strings.
Missing pricing, missing usage, or invalid token counts produce a per-message
`reason` and `cost_details: null`; the conversation then has `complete: false` and
`total_cost: null`. `known_cost` is the subtotal for calls that can be priced.
An empty conversation costs zero. The bundled catalog ships provider list
prices (checked 2026-10-14); a comment on an entry flags tiered or promotional
rates that a single per-token rate cannot capture.

This is an estimate of **retained checkpoint usage**, not a billing ledger:
failed/unrecorded calls and pruned message writes cannot be reconstructed.
If checkpoints exist but all task writes are unavailable, calculation fails
instead of recording a false zero.
Legacy messages without IDs are deduplicated by serialized content, which may
merge identical calls. Reading a long history still takes work; avoid polling the live endpoint at
streaming frequency.

## Project Structure

```
backend/
├── app/
│   ├── adapters/          # Message and stream adapters
│   ├── api/
│   │   ├── routes/        # API endpoints
│   │   │   ├── agents.py
│   │   │   ├── mcp_servers.py
│   │   │   ├── oauth.py
│   │   │   └── threads.py
│   │   └── main.py        # API router
│   ├── models/            # Data models
│   └── main.py            # FastAPI app & lifespan
├── tests/                 # Test suite
├── example_callback_handler.py
├── test_oauth_flow.py
├── OAUTH_REDIS_FLOW.md
├── pyproject.toml
└── README.md
```

## OAuth Flow with Redis

The OAuth flow uses Redis pub/sub for callback handling. See [OAUTH_REDIS_FLOW.md](./OAUTH_REDIS_FLOW.md) for detailed documentation.

### Quick Overview

1. **Start OAuth flow**: GET `/mcp-servers/{id}/list-tools` returns authorization URL and state
2. **User authorizes**: Visit the authorization URL in browser
3. **Callback received**: OAuth provider redirects to `/mcp-servers/{id}/callback`
4. **Redis pub/sub**: Callback publishes code to `auth:callback:{state}` channel
5. **Handler receives**: Any subscriber to that channel receives the code

### Example: Testing OAuth Flow

```bash
# Terminal 1: Start the test (will wait for callback)
python test_oauth_flow.py notion

# Follow the authorization URL in your browser
# The test will automatically receive the code via Redis
```

### Example: Manual Callback Handler

```bash
# Terminal 1: Start callback handler
python example_callback_handler.py <state-from-oauth-start>

# Terminal 2: Complete OAuth in browser
# When callback hits, Terminal 1 will receive the code
```

## API Endpoints

### MCP Servers

- `GET /mcp-servers/` - List all available MCP servers
- `GET /mcp-servers/{id}/list-tools` - List tools (triggers OAuth if needed)
- `GET /mcp-servers/{id}/callback` - OAuth callback endpoint

### Threads

- `POST /threads/` - Create a new conversation thread
- `POST /threads/{thread_id}/stream` - Stream agent responses
- `GET /threads/{thread_id}` - Get thread details

### Agents

- `GET /agents/` - List all agents
- `GET /agents/{agent_id}` - Get agent details

## Sorties structurées (structured output)

Un run peut fournir un `output_schema` (JSON Schema) pour obtenir une réponse validée dans `structured_response`. Le schéma est géré par `DeferredStructuredOutputMiddleware` (`app/agents/structured_output.py`).

**Le schéma n'est pas appliqué pendant la boucle ReAct.** Contraindre le décodage à chaque appel casse la boucle en pratique : le modèle arrête d'appeler les outils et remplit directement le schéma avec des valeurs inventées. Le middleware laisse donc la boucle tourner sans contrainte, puis applique le schéma sur **un seul dernier tour de formatage**, une fois la réponse finale atteinte.

Sur ce tour de formatage, langchain résout le schéma par défaut en **`ToolStrategy`** : un appel d'outil forcé (`tool_choice` = `"required"` ou une fonction nommée). Cela fonctionne pour la plupart de nos fournisseurs, mais deux APIs rejettent l'appel forcé. La stratégie de formatage est donc choisie par fournisseur via `PROVIDER_FORMAT_MODES` (`app/agents/structured_output.py`) — un fournisseur absent utilise l'appel d'outil forcé par défaut.

| Mode | Fournisseur | Comment |
| --- | --- | --- |
| `FORMAT_TOOL` (défaut) | OpenAI, Anthropic, Google, Xiaomi, OpenRouter… | Appel d'outil forcé (`ToolStrategy`). Le fournisseur garantit le schéma. |
| `FORMAT_PROVIDER_NATIVE` | Meta | `ProviderStrategy` → `response_format: {type: "json_schema"}`. |
| `FORMAT_JSON_OBJECT` | DeepSeek | `response_format: {type: "json_object"}` + validation locale. |

### Le cas Meta

L'API de Meta (`muse-spark-1.2`) n'accepte que `tool_choice="auto"` et rejette l'appel forcé avec une erreur 400. On formate donc via la **stratégie native** (`ProviderStrategy` → `response_format: {type: "json_schema"}`), qui ne force aucun `tool_choice`.

### Le cas DeepSeek (mode raisonnement)

DeepSeek avec le raisonnement activé (`thinking.type = "enabled"`) rejette **à la fois** l'appel forcé (`Thinking mode does not support this tool_choice`) **et** le `json_schema` (`This response_format type is unavailable now`). Seul le mode `json_object` (legacy) fonctionne : il ne garantit que « c'est du JSON », pas la forme. Le middleware embarque donc le schéma dans le prompt, lie `response_format: {type: "json_object"}`, puis **parse et valide le JSON lui-même** (`validate_structured_response`, avec la même boucle de retry). C'est la seule voie où l'enforcement du schéma vient de nous et non du fournisseur.

### Pourquoi ne pas utiliser une voie unique partout ?

Parce que `ToolStrategy` (le défaut de langchain) fonctionne déjà chez la plupart des fournisseurs. On ne dévie de la stratégie que là où l'appel forcé échoue réellement (Meta, DeepSeek en raisonnement), afin de garder un impact minimal et de ne pas risquer de régression sur les fournisseurs qui marchent aujourd'hui. Ajouter un fournisseur se résume à une ligne dans `PROVIDER_FORMAT_MODES`.

## Configuration

### Environment Variables

Create a `.env` file in the backend directory:

```env
# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# API Configuration
OPENAI_API_KEY=your_openai_api_key

# OAuth Configuration (if using custom settings)
OAUTH_REDIRECT_BASE_URL=http://localhost:8000
```

### Adding MCP Servers

Edit `app/main.py` to add new MCP servers:

```python
app.state.mcp_servers = [
    {
        "id": "my-server",
        "name": "My Server",
        "url": "https://api.example.com/mcp",
        "icon": "https://example.com/icon.png",
        "requiresOAuth": False
    }
]
```

## Testing

Run the test suite:

```bash
uv run pytest
```

Run specific test:

```bash
uv run pytest tests/adapters/test_message_adapter.py
```

Test Redis pub/sub functionality:

```bash
python test_oauth_flow.py test-redis
```

## Development

### Code Quality

The project uses Ruff for linting and formatting:

```bash
# Check code
uv run ruff check .

# Format code
uv run ruff format .

# Fix auto-fixable issues
uv run ruff check --fix .
```

### Hot Reload

FastAPI dev mode includes hot reload:

```bash
uv run fastapi dev app/main.py
```

Changes to Python files will automatically reload the server.

## Docker Support

### Redis Only (Recommended for Development)

```bash
# From project root
docker compose up -d
```

### Full Stack (Future)

A complete Docker setup for the entire backend will be added in the future.

## Troubleshooting

### Redis Connection Issues

```bash
# Check if Redis is running
docker compose ps

# View Redis logs
docker compose logs redis

# Test connection
redis-cli ping

# Restart Redis
docker compose restart redis
```

### Port Already in Use

If port 8000 is already in use:

```bash
# Use a different port
uv run fastapi dev app/main.py --port 8001
```

### Import Errors

```bash
# Reinstall dependencies
uv sync --force

# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} +
```

### OAuth Callback Not Received

1. Ensure Redis is running: `docker compose ps`
2. Check callback handler is listening BEFORE authorization
3. Verify state parameter matches between start and callback
4. Check timeout settings (default: 300 seconds)

## Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes and test: `uv run pytest`
3. Format code: `uv run ruff format .`
4. Commit changes: `git commit -am 'Add my feature'`
5. Push: `git push origin feature/my-feature`
6. Create a Pull Request

## License

[Add your license here]

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Redis Pub/Sub Documentation](https://redis.io/docs/manual/pubsub/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
