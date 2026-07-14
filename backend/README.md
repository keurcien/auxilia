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

Sur ce tour de formatage, langchain résout le schéma en **`ToolStrategy`** : un appel d'outil forcé (`tool_choice` = `"required"` ou une fonction nommée). Cela fonctionne pour tous nos fournisseurs **sauf Meta**.

### Le cas Meta

L'API de Meta (`muse-spark-1.1`) n'accepte que `tool_choice="auto"` et rejette l'appel forcé avec une erreur 400. Pour les fournisseurs listés dans `AUTO_ONLY_TOOL_CHOICE_PROVIDERS` (`app/model_providers/catalog.py`), on formate donc via la **stratégie native** (`ProviderStrategy` → `response_format: {type: "json_schema"}`), qui ne force aucun `tool_choice`. Ajouter un fournisseur « auto-only » se résume à une ligne dans ce frozenset.

### Pourquoi ne pas utiliser la voie native partout ?

Parce que `ToolStrategy` (le défaut de langchain) fonctionne déjà chez tous les autres fournisseurs. On ne remplace la stratégie que là où l'appel forcé échoue réellement (Meta), afin de garder un impact minimal et de ne pas risquer de régression sur les fournisseurs qui marchent aujourd'hui.

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
