# Sandboxes as workspace resources — design plan

Status: **proposal** (nothing implemented). Companion to the MCP server pattern it deliberately mirrors.

## 1. Goal & framing

Today the sandbox is a **deployment-wide singleton**: `SANDBOX_PROVIDER` (env) picks `opensandbox` or `cloudrun` once per backend instance (`app/sandbox/settings.py:13`), and agents opt in with a bare boolean (`AgentDB.has_code_interpreter`). One deployment can never mix providers, and "code execution" is a feature flag, not a resource.

The direction of the ecosystem is *plugins*: MCP servers, skills, sandboxes as first-class capabilities you register once at the workspace level and attach to agents. MCP servers already follow that shape in auxilia (`mcp_servers` table → `agent_mcp_servers` binding → resolved at `Toolset.prepare`). This plan gives sandboxes the same shape:

- a **`sandboxes` table** — workspace-level registry of configured sandbox backends (the deepagents-supported providers exist as rows by default, seeded from env),
- an **`agent_sandboxes` binding table** — mirroring `agent_mcp_servers`, saved through the same atomic `PUT /agents/{id}/config`,
- **runtime resolution** — `ResolvedAgent.resolve` picks the bound row and builds the matching provider, replacing the global `get_provider()`.

Result: opensandbox and cloudrun coexist in one workspace; each agent targets its own execution backend.

## 2. Concept model

```
┌─────────────────────────── workspace ───────────────────────────┐
│                                                                  │
│  mcp_servers                sandboxes                            │
│  ┌──────────────┐           ┌───────────────────────────┐        │
│  │ Linear (oauth)│          │ Python (opensandbox) [env] │       │
│  │ Sheets (oauth)│          │ Data lab (cloudrun)        │       │
│  └──────┬───────┘           └────────────┬──────────────┘        │
│         │ agent_mcp_servers              │ agent_sandboxes       │
│         │ (N per agent, tools map)       │ (≤1 per agent, tools  │
│         ▼                                ▼  map)                 │
│      ┌──────────────────── agents ────────────────────┐          │
│      └────────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

Vocabulary (prose): a **sandbox** is the workspace resource (a configured backend); a **sandbox session** is the runtime instance the model creates/connects via `create_sandbox` / `connect_sandbox`.

Deliberate asymmetry with MCP: an agent binds **at most one** sandbox. deepagents' `create_deep_agent(backend=...)` accepts exactly one `BaseSandbox`; pretending otherwise would be API fiction. The binding still lives in a link table (not a nullable FK on `agents`) so it carries per-binding config (`tools` status map, later: package overrides) and so the constraint can be relaxed when a `CompositeBackend` story exists. The config payload is list-shaped (`sandboxes: [...]`, max length 1) so the API doesn't change when that day comes.

## 3. Data model

### 3.1 `sandboxes` (new, in `app/sandbox/models.py`)

```python
class SandboxProviderType(str, Enum):
    opensandbox = "opensandbox"
    cloudrun = "cloudrun"

class SandboxBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    description: str | None = None
    provider: SandboxProviderType = Field(nullable=False)
    config: dict = Field(sa_column=Column(JSONB, nullable=False))   # non-secret, provider-specific
    is_active: bool = Field(default=True)

class SandboxDB(SandboxBase, BaseDBModel, table=True):
    __tablename__ = "sandboxes"
    source: SandboxSource = Field(default=SandboxSource.workspace)  # env | workspace
    encrypted_secrets: str | None = None                            # AES-GCM blob (JSON of secret fields)
```

- `config` is validated by a **discriminated union** of pydantic models keyed on `provider` — `OpenSandboxConfig` (domain, default_image, default_packages, timeout, volume_mounts, use_server_proxy) and `CloudRunConfig` (gateway_url, gcs_bucket, snapshot_prefix, allow_egress, default_packages, timeout). These are the row-level twins of today's env `*Settings` classes, which survive only as the bootstrap source (§3.3).
- `encrypted_secrets` holds the sensitive fields (`api_key` for opensandbox, `gateway_secret` for cloudrun), encrypted like MCP API keys. Lift the AES-GCM helpers from `app/mcp/servers/encryption.py` into `app/utils/encryption.py` (re-export from the old path) rather than importing `mcp.servers` from `sandbox`.
- `source = "env"` rows are synced from environment at startup and read-only in the UI; `"workspace"` rows are admin-managed.

### 3.2 `agent_sandboxes` (new, in `app/agents/models.py`, next to `AgentMCPServerDB`)

```python
class AgentSandboxBase(SQLModel):
    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", nullable=False)
    sandbox_id: UUID = Field(foreign_key="sandboxes.id", nullable=False)
    tools: dict[str, ToolStatus] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

class AgentSandboxDB(AgentSandboxBase, BaseDBModel, table=True):
    __tablename__ = "agent_sandboxes"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_sandbox"),)   # one per agent, v1
```

`tools` reuses the existing `ToolStatus` enum over the sandbox's *static* tool surface — `create_sandbox`, `connect_sandbox`, `execute` (the deepagents file tools stay ungated) — so `execute` can be set to `needs_approval` or `disabled` exactly like an MCP tool. Unlike MCP there is no discovery/sync step: the tool list is known at import time, so `tools=None` simply means "all `always_allow`".

### 3.3 Migration & default rows ("deepagents backends exist by default")

One alembic revision:

1. Create both tables.
2. **Seed the env default row**: instantiate today's `SandboxSettings` (env is present wherever `alembic upgrade head` runs — same container); if `enabled` is true, insert one `SandboxDB` row (`source="env"`, name `"OpenSandbox"` / `"Cloud Run"`) carrying the env config + encrypted secrets.
3. **Convert the flag**: for every agent with `has_code_interpreter = true`, insert an `agent_sandboxes` row pointing at the seeded row. If no provider was configured, the flag was already a no-op (tools never appeared) — drop it silently.
4. Drop `agents.has_code_interpreter`.

Plus an idempotent **startup sync** (`sync_env_sandboxes()` in the FastAPI lifespan, sibling of the trigger scanner startup): upsert/update `source="env"` rows from env on every boot. This keeps env-driven deployments working with zero new configuration — the env vars now *materialize* a registry row instead of being read at call time — and handles env being configured after the migration ran.

## 4. Backend API surface

### 4.1 Workspace registry — `app/sandbox/` grows the standard layer stack

`models.py`, `schemas.py`, `repository.py`, `service.py` (`SandboxService(BaseService[SandboxDB, SandboxRepository])`), and `router.py` replaces the current one-liner status router:

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `GET /sandboxes` | any user | list active rows (id, name, description, provider, source) — what the agent editor consumes |
| `POST /sandboxes` | `require_admin` | provider-discriminated create; secrets write-only |
| `GET /sandboxes/{id}` | `require_admin` | full config, secrets redacted to a hint (mirror `oauth-secret-hint`) |
| `PATCH /sandboxes/{id}` | `require_admin` | rejected for `source="env"` rows |
| `DELETE /sandboxes/{id}` | `require_admin` | blocked (400) while `agent_sandboxes` rows reference it |

`GET /sandbox/status` is deleted; its only caller (`add-agent-tool-dialog.tsx`) switches to `GET /sandboxes` (enabled ⇔ non-empty).

### 4.2 Agent binding — `app/agents/sandboxes/`, a mirror of `app/agents/mcp_servers/`

`AgentSandboxService.set_for_agent(agent_id, configs)` — same whole-set replace semantics as `AgentMCPServerService.set_for_agent` (`app/agents/mcp_servers/service.py:104`), minus tool discovery. Wired into both orchestration sites in `AgentService`:

- `set_config` (`app/agents/core/service.py:290`) — one new line after `mcp_server_service.set_for_agent(...)`
- `create_from_config` (`:169`) — ditto

Schema changes (`app/agents/schemas.py`):

```python
class AgentSandboxConfig(SQLModel):
    sandbox_id: UUID
    tools: dict[str, ToolStatus] | None = None

class AgentConfig(SQLModel):
    ...                                   # has_code_interpreter removed
    sandboxes: list[AgentSandboxConfig] = []   # validator: len ≤ 1

class AgentResponse(SQLModel):
    ...
    sandboxes: list[AgentSandboxResponse] | None = None   # binding + resolved name/provider for the UI
```

`AgentRepository.list_with_permissions` gains the same outer-join treatment `agent_mcp_servers` gets today so `_group_rows`/`_assemble` can hydrate `sandboxes` without an N+1.

## 5. Runtime resolution

### 5.1 Providers become instance-configured

Today both providers read the global (`sandbox_settings.opensandbox` / `.cloudrun`) inside their methods. Refactor:

```python
class OpenSandboxProvider:
    def __init__(self, config: OpenSandboxConfig): ...
class CloudRunProvider:
    def __init__(self, config: CloudRunConfig): ...

def build_provider(sandbox: SandboxDB, secrets: dict) -> SandboxProvider:
    # discriminated on sandbox.provider; validates row config into the typed model
```

(`build_*`, not `make_*` — CONVENTIONS.md §2.) `get_provider()` and the module-global `SandboxSettings` facade disappear; the env `*Settings` classes remain only as input to `sync_env_sandboxes()`.

`create_sandbox_tools(lazy_backend)` becomes `create_sandbox_tools(lazy_backend, provider)` — the provider is injected instead of resolved from the global inside (`app/sandbox/tools.py:18`).

### 5.2 `ResolvedAgent` carries the sandbox

Resolution happens where everything else DB-bound happens — `ResolvedAgent.resolve` (`app/agents/runtime.py:162`), which already has the request-scoped `db`:

```python
@dataclass
class ResolvedSandbox:
    provider: SandboxProvider          # built from the row, secrets already decrypted
    tools: dict[str, ToolStatus] | None

@dataclass
class ResolvedAgent:
    config: AgentResponse
    prepared: PreparedToolset
    sandbox: ResolvedSandbox | None = None
```

`resolve()` reads the binding (via `AgentResponse.sandboxes`), loads + decrypts the `SandboxDB` row through `SandboxService`, and stashes a ready `ResolvedSandbox`. Nothing downstream (streaming scope, runs worker, subagent compile) touches the DB or a global.

The two gate sites change from

```python
sandbox = self.config.has_code_interpreter and sandbox_settings.enabled     # runtime.py:187, :318
```

to

```python
sandbox = self.sandbox is not None    # binding exists ∧ row is_active — enforced at resolve
```

and `build_runnable` / `Agent._setup` pass `self.sandbox.provider` into `create_sandbox_tools`. Tool gating: `disabled` entries are dropped from the toolset; `needs_approval` entries join the same HITL wiring MCP tools use (parent agent only, same subagent limitation as today).

**Session provenance caveat**: `connect_sandbox(id)` reconnects through whatever provider the agent is bound to *now*. If an admin swaps an agent's sandbox mid-thread, old session ids fail — the tool already degrades gracefully ("Failed to reconnect… create a new sandbox instead"), which is the intended behavior. No cross-provider id namespacing in v1.

Triggers, Slack, and the durable runs worker all flow through `ResolvedAgent.resolve`, so they inherit this for free.

## 6. Frontend design

### 6.1 Agent editor — sandbox card inside the TOOLS section

The sandbox stays where "Code execution" lives today: the TOOLS right-rail section (`agent-tool-list.tsx`). The static built-in row (`agent-code-execution.tsx`) is replaced by an `AgentSandbox` card — same skeleton as `agent-mcp-server.tsx:199` so the rail reads as one system:

```
TOOLS 3                                          + Add tool
┌────────────────────────────────────────────────────────┐
│ ⬒  Linear                                          ›   │   ← MCP card (unchanged)
├────────────────────────────────────────────────────────┤
│ ▣  Data lab              [CLOUD RUN]               ˅   │   ← sandbox card
│  ──────────────────────────────────────────────────    │
│   Create sandbox      Start a new session   [●│○│○]    │
│   Connect sandbox     Reattach by ID        [●│○│○]    │
│   Execute             Run shell commands    [○│●│○]    │   ← needs_approval
│  ──────────────────────────────────────────────────    │
│                  Disable Data lab                       │
└────────────────────────────────────────────────────────┘
```

- **Icon tile**: same `size-[26px] rounded-[6px] border` square, but a lucide glyph (`SquareTerminal`) instead of an `Image` — sandboxes have no `icon_url`.
- **Provider pill**: reuse the status-pill recipe (`rounded-[4px] px-2 py-0.5 font-mono text-[9.5px]`) in a neutral tint — `OPENSANDBOX` / `CLOUD RUN`. This is the one visual element MCP cards don't have, and it's the point: it answers "where does this agent's code run".
- **Tool rows**: reuse `agent-mcp-tool.tsx` + `ThreeStateToggle` verbatim over the static 3-tool list (descriptions hardcoded client-side).
- **Footer**: same "Disable {name}" removal affordance; no per-card switch, matching MCP cards.
- Expansion is local `useState` per card, `readOnly` threads down, exactly as the MCP card does.

**Add tool dialog** (`add-agent-tool-dialog.tsx`): the "built-in capability" `Switch` block is replaced by a `SANDBOXES` section under the MCP grid — same `font-mono text-[10.5px] tracking-[0.09em]` heading, same 2-col card grid (`AvailableMCPServerCard` generalized: glyph tile + name + provider pill + `+` button). Because of the one-per-agent rule, the whole section hides once a sandbox is bound (and reappears on removal) — the same "list shrinks as you add" behavior the MCP grid has. Section absent entirely when `GET /sandboxes` is empty.

### 6.2 Form state & save

Extend the four canonical helpers in `agents/lib/agent-form.ts` (`defaultAgentForm`, `fromAgent`, `toPayload`, `isFormDirty`):

```ts
export interface AgentSandboxForm { sandboxId: string; tools: Record<string, ToolStatus> | null }
export interface AgentFormState {
  ...                            // hasCodeInterpreter removed
  sandboxes: AgentSandboxForm[]; // length ≤ 1
}
```

`toPayload` includes `sandboxes` (sorted, tool keys sorted) so dirtiness and the UNSAVED badge track it; the axios `PRESERVE_KEYS_FIELDS = ["tools", ...]` already protects the status map's keys from case conversion. `types/agents.ts` gains `Sandbox`, `AgentSandbox` (binding + resolved name/provider), and `Agent.sandboxes`. The editor fetches `GET /sandboxes` alongside its existing `GET /mcp-servers` call in `agent-tool-list.tsx:39`.

### 6.3 Workspace admin page — `/sandboxes`

Sibling of the MCP servers page, powered by the shared DataTable (Petrol Mono kit):

```
SANDBOXES 2                                      + Add sandbox
┌──────────────┬─────────────┬──────────────────────┬────────┬──────────┐
│ NAME         │ PROVIDER    │ RUNTIME              │ AGENTS │ SOURCE   │
├──────────────┼─────────────┼──────────────────────┼────────┼──────────┤
│ OpenSandbox  │ OPENSANDBOX │ python:3.12-slim     │ 4      │ env ⚿    │
│ Data lab     │ CLOUD RUN   │ gateway: sbx-gw…run… │ 1      │          │
└──────────────┴─────────────┴──────────────────────┴────────┴──────────┘
```

Create/edit dialog: provider `Select` first, then the provider-specific field group (opensandbox: domain, API key, image, packages, timeout; cloudrun: gateway URL, secret, GCS bucket, egress). Secrets are write-only with a stored hint, mirroring the MCP OAuth-secret UX. `source: env` rows render read-only with a "Managed by environment" note. Delete is blocked with an "in use by N agents" message.

## 7. Rollout phases

1. **Registry + runtime plumbing (backend, behavior-identical)** — tables, migration + flag conversion, `sync_env_sandboxes()` startup sync, shared encryption util, provider instance-config refactor, `ResolvedAgent.sandbox`, `AgentConfig.sandboxes` + `AgentSandboxService.set_for_agent`, `AgentResponse.sandboxes`, `GET /sandboxes` (read-only), drop `/sandbox/status`. An env-configured deployment upgrades with zero config changes and identical behavior.
2. **Agent editor UI** — form-state plumbing, sandbox card in TOOLS, add-dialog SANDBOXES section, read-mode rendering, tool-status gating (disabled + HITL on `execute`).
3. **Workspace sandbox management** — admin CRUD endpoints, `/sandboxes` page, secrets handling, optional connectivity probe (`execute("true")` smoke test).
4. **Later** — relax `uq_agent_sandbox` + CompositeBackend for multi-sandbox agents; per-binding package/image overrides; skills as the third plugin type on the same registry-plus-binding shape.

## 8. Open questions

- **Subagents**: today each agent's own flag governs its sandbox; bindings keep that per-agent semantics (a supervisor's sandbox is not inherited). Confirm that's still wanted once cloudrun snapshots-per-subagent exist (known persist gap).
- **`AgentPatch.has_code_interpreter` callers**: the legacy `POST /agents` + `PATCH` fields are dropped in phase 1 — pre-1.0 breaking is fine per release-please rules (`feat!` bumps minor), but the PR must be titled accordingly.
- **Env rows vs. UI edits**: `source="env"` rows being read-only is the simple contract; alternative (editable, env only bootstraps once) means env changes stop propagating. Recommend read-only.
