# Sandboxes as workspace resources — design plan

Status: **proposal, v2** (nothing implemented). v1 treated env vars as the primary configuration source with UI management bolted on later; v2 inverts that: **sandboxes are configured in the UI**, like MCP servers, and env is only a one-shot migration input. v2 also adds the config anatomy (shared base, single URL + secret shape) and Daytona as the third provider.

## 1. Goal & framing

Today the sandbox is a **deployment-wide singleton**: `SANDBOX_PROVIDER` (env) picks `opensandbox` or `cloudrun` once per backend instance (`app/sandbox/settings.py:13`), each provider has its own env prefix (`OPEN_SANDBOX_*` vs `CLOUD_RUN_SANDBOX_*`), and agents opt in with a bare boolean (`AgentDB.has_code_interpreter`). One deployment can never mix providers, adding a second opensandbox VM or a second Cloud Run gateway is impossible, and every change is a redeploy.

The dividing line this plan follows (the industry-standard one — n8n credentials, Dify model providers, and auxilia's own MCP servers all sit on it):

- **Env** = singleton deployment infrastructure the *operator* owns: DB URL, Redis, the secrets-encryption `SALT`. Needed at boot, exactly one per deployment.
- **UI + encrypted DB rows** = workspace resources the *admin* manages at runtime: things there can be N of, carrying third-party credentials. MCP servers already work exactly this way, with zero env configuration.

Sandboxes are the second species of the same genus as MCP servers — a name, an endpoint, a credential — so they get the same treatment:

- a **`sandboxes` table** — workspace registry, admin CRUD in the UI, secrets encrypted with the existing Fernet/`SALT` machinery,
- an **`agent_sandboxes` binding table** — mirroring `agent_mcp_servers`, saved through the same atomic `PUT /agents/{id}/config`,
- **runtime resolution** — `ResolvedAgent.resolve` picks the bound row and builds the matching provider; the global `get_provider()` and both env `*Settings` classes are deleted,
- **three providers**: `opensandbox`, `cloudrun`, `daytona` — the third proving the abstraction costs one class + one registry entry.

## 2. Concept model

```
┌─────────────────────────── workspace ────────────────────────────┐
│                                                                   │
│  mcp_servers                sandboxes                             │
│  ┌──────────────┐           ┌────────────────────────────┐        │
│  │ Linear (oauth)│          │ Python VM (opensandbox)     │       │
│  │ Sheets (oauth)│          │ Data lab (cloudrun)         │       │
│  └──────┬───────┘           │ Daytona US (daytona)        │       │
│         │                   └────────────┬───────────────┘        │
│         │ agent_mcp_servers              │ agent_sandboxes        │
│         │ (N per agent, tools map)       │ (≤1 per agent, tools   │
│         ▼                                ▼  map)                  │
│      ┌──────────────────── agents ────────────────────┐           │
│      └────────────────────────────────────────────────┘           │
└───────────────────────────────────────────────────────────────────┘
```

Vocabulary (prose): a **sandbox** is the workspace resource (a configured backend); a **sandbox session** is the runtime instance the model creates/connects via `create_sandbox` / `connect_sandbox`.

An agent binds **at most one** sandbox (deepagents' `create_deep_agent(backend=...)` takes exactly one `BaseSandbox`). The binding still lives in a link table so it carries per-binding config (`tools` status map) and so the constraint can be relaxed later; the config payload is list-shaped (`sandboxes: [...]`, max 1) so the API doesn't change when that day comes.

## 3. How a sandbox config is saved

### 3.1 Anatomy — every provider is the same three-part shape

Look at what the three providers actually need and the DRY shape falls out. Today's divergent env names hide it:

| | endpoint (`url`) | credential (`secret`) | provider extras (`config` JSONB) |
| --- | --- | --- | --- |
| **opensandbox** | `OPEN_SANDBOX_DOMAIN` | `OPEN_SANDBOX_API_KEY` (optional) | `default_image`, `volume_mounts`, `use_server_proxy` |
| **cloudrun** | `CLOUD_RUN_SANDBOX_GATEWAY_URL` | `CLOUD_RUN_SANDBOX_GATEWAY_SECRET` (required) | `gcs_bucket`, `snapshot_prefix`, `allow_egress` |
| **daytona** | API URL (default `https://app.daytona.io/api`) | API key (required) | `target` (region), `snapshot`/image, `auto_stop_interval` |

Plus two knobs every provider shares: `default_packages` and `timeout`. So: **endpoint + one credential + shared runtime defaults + a small provider-specific remainder.** That's the storage schema, the pydantic base class, and the create-dialog layout, all at once.

### 3.2 Table — first-class columns for the shared shape, JSONB for the remainder

```python
# app/sandbox/models.py
class SandboxProviderType(str, Enum):
    opensandbox = "opensandbox"
    cloudrun = "cloudrun"
    daytona = "daytona"

class SandboxBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    description: str | None = None
    provider: SandboxProviderType = Field(nullable=False)
    url: str = Field(nullable=False)                                 # the endpoint, plain
    config: dict = Field(default={}, sa_column=Column(JSONB, nullable=False))  # extras only

class SandboxDB(SandboxBase, BaseDBModel, table=True):
    __tablename__ = "sandboxes"
    encrypted_secret: str | None = None                              # the one credential, Fernet
```

Design decisions, and why:

- **`url` is a real column, not a JSONB key.** Every provider has exactly one endpoint; promoting it gives the admin table a display column, allows a uniqueness check if wanted, and means the generic parts of the UI never dig into provider-specific JSON. This mirrors `MCPServerDB.url`.
- **One `encrypted_secret` column, not an encrypted-JSON-secrets blob.** Every provider has exactly one credential (opensandbox's being optional). A single nullable column reuses the MCP pattern verbatim — encrypt with the existing `encrypt_value`/`decrypt_value` (Fernet, key derived from the `SALT` env var; lift them from `app/mcp/servers/encryption.py` to `app/utils/encryption.py` with re-exports, so `sandbox` doesn't import from `mcp.servers`). No new crypto machinery, no partial-JSON-update headaches on rotation.
- **`config` holds only the provider-specific remainder** (plus the two shared knobs — see the base model below). It is always validated through the typed union before it touches the DB, so JSONB here is a serialization detail, not a schema escape hatch.

### 3.3 Typed config — one base class, three thin subclasses

The env `*Settings` classes are replaced by API-facing config models. The base carries everything shared; subclasses add only their remainder:

```python
# app/sandbox/schemas.py
class SandboxConfigBase(SQLModel):
    """Shared shape of every sandbox provider's runtime config.
    Hydrated from a SandboxDB row: url/secret from columns, rest from JSONB."""
    # Unknown keys are rejected, not silently dropped — this is what makes
    # the config JSONB "always validated", not a schema escape hatch.
    model_config = ConfigDict(extra="forbid")

    url: str
    secret: str | None = None            # decrypted at hydration, never serialized in responses
    default_packages: list[str] = []
    timeout: int = 30 * 60

class OpenSandboxConfig(SandboxConfigBase):
    provider: Literal["opensandbox"] = "opensandbox"
    default_image: str = "python:3.12-slim"
    volume_mounts: list[str] = []
    use_server_proxy: bool = True

class CloudRunConfig(SandboxConfigBase):
    provider: Literal["cloudrun"] = "cloudrun"
    gcs_bucket: str | None = None
    snapshot_prefix: str = "sandbox-snapshots/"
    allow_egress: bool = False

    @model_validator(mode="after")
    def require_secret(self):            # was: the fail-closed `enabled` check at boot
        if not self.secret:
            raise ValueError("Cloud Run sandboxes require a gateway secret")
        return self

class DaytonaConfig(SandboxConfigBase):
    provider: Literal["daytona"] = "daytona"
    url: str = "https://app.daytona.io/api"
    target: str = "us"
    snapshot: str | None = None
    auto_stop_interval: int = 15         # minutes; verify against the SDK at implementation

    # validator: secret (API key) required

SandboxConfig = Annotated[
    OpenSandboxConfig | CloudRunConfig | DaytonaConfig,
    Field(discriminator="provider"),
]
```

- **Validation replaces the old boot-time `enabled` gate.** Today `SandboxSettings.enabled` fails closed when cloudrun lacks its gateway secret; that logic moves into the config models and runs at `POST /sandboxes` / `PATCH` time — an admin cannot *save* an incomplete sandbox, which is strictly better than discovering it at boot.
- **Hydration is one function**: `build_config(row: SandboxDB) -> SandboxConfig` — validates `{url, secret: decrypt(row.encrypted_secret), **row.config}` through the discriminated union. Persistence is its inverse: split the validated model back into `url` / `encrypted_secret` / remainder-JSONB.
- **Secret lifecycle** mirrors MCP OAuth secrets: write-only on create/patch (omitted field = keep current), never present in any `*Response`, `GET /sandboxes/{id}/secret-hint` for the masked hint, rotating = send a new value, re-encrypted on save.

### 3.4 Provider runtime — one base class, a registry, three entries

Today both providers read the module-global `sandbox_settings` inside their methods and duplicate the create/install/message choreography. Refactor to a template-method base plus a registry:

```python
# app/sandbox/provider.py
class BaseSandboxProvider(ABC):
    config_cls: ClassVar[type[SandboxConfigBase]]

    def __init__(self, config: SandboxConfigBase):
        self.config = config

    def create(self, *, timeout_minutes: int) -> tuple[BaseSandbox, str]:
        backend = self._create_backend(timeout_minutes=timeout_minutes)
        install_default_packages(backend, self.config.default_packages)   # shared, once
        return backend, self._describe(backend, created=True)

    @abstractmethod
    def _create_backend(self, *, timeout_minutes: int) -> BaseSandbox: ...

    @abstractmethod
    def connect(self, sandbox_id: str) -> tuple[BaseSandbox, str]: ...


PROVIDERS: dict[SandboxProviderType, type[BaseSandboxProvider]] = {
    SandboxProviderType.opensandbox: OpenSandboxProvider,
    SandboxProviderType.cloudrun: CloudRunProvider,
    SandboxProviderType.daytona: DaytonaProvider,
}

def build_provider(row: SandboxDB) -> BaseSandboxProvider:
    cls = PROVIDERS[row.provider]
    return cls(build_config(row))
```

- deepagents only ships the abstract `BaseSandbox` — `OpenSandbox` and `CloudRunSandbox` are already ours. **Daytona** is one more `BaseSandbox` implementation (`app/sandbox/daytona/`) wrapping the Daytona Python SDK: `Daytona(DaytonaConfig(api_key=secret, api_url=url, target=...))`, `daytona.create(...)` / `daytona.get(sandbox_id)` for the provider's create/connect, `sandbox.process.exec(...)` behind `execute`, `sandbox.fs.*` behind upload/download. (SDK surface from docs; verify exact names at implementation time.)
- **Adding a provider = the DRY test**: one `BaseSandbox` subclass, one `BaseSandboxProvider` subclass, one config model in the union, one `PROVIDERS` entry, one field-group spec for the create dialog (§6.3). No schema change, no new env vars, no changes to tools/runtime/binding code.
- `create_sandbox_tools(lazy_backend)` becomes `create_sandbox_tools(lazy_backend, provider)` (`app/sandbox/tools.py:18`); `get_provider()` and the `SandboxSettings.enabled` gate are deleted from the runtime path; the env settings classes themselves survive untouched solely as the one-shot migration's input (§7) and die with the env vars once every deployment has upgraded.

## 4. Agent binding

Unchanged from v1 in substance — mirroring `agent_mcp_servers`:

```python
# app/agents/models.py, next to AgentMCPServerDB
class AgentSandboxBase(SQLModel):
    agent_id: UUID = Field(foreign_key="agents.id", ondelete="CASCADE", nullable=False)
    sandbox_id: UUID = Field(foreign_key="sandboxes.id", nullable=False)
    tools: dict[str, ToolStatus] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

class AgentSandboxDB(AgentSandboxBase, BaseDBModel, table=True):
    __tablename__ = "agent_sandboxes"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_sandbox"),)   # one per agent, v1
```

- `tools` reuses `ToolStatus` over the static tool surface — `create_sandbox`, `connect_sandbox`, `execute` (deepagents file tools stay ungated) — so `execute` can be `needs_approval` or `disabled` like an MCP tool. No discovery step; `tools=None` means all `always_allow`.
- `app/agents/sandboxes/` mirrors `app/agents/mcp_servers/`: `AgentSandboxService.set_for_agent(agent_id, configs)` with the same whole-set replace semantics (`app/agents/mcp_servers/service.py:104`), minus tool sync. Wired into both orchestration sites: `AgentService.set_config` (`app/agents/core/service.py:290`) and `create_from_config` (`:169`).
- `AgentConfig` gains `sandboxes: list[AgentSandboxConfig] = []` (validator: len ≤ 1) and drops `has_code_interpreter`; `AgentResponse` gains `sandboxes: list[AgentSandboxResponse]` (binding + resolved name/provider for the UI), hydrated via the same outer-join treatment `agent_mcp_servers` gets in `AgentRepository.list_with_permissions`.

## 5. Runtime resolution

Resolution happens where everything DB-bound already happens — `ResolvedAgent.resolve` (`app/agents/runtime.py:162`):

```python
@dataclass
class ResolvedSandbox:
    provider: BaseSandboxProvider        # built via build_provider(row), secret already decrypted
    tools: dict[str, ToolStatus] | None

@dataclass
class ResolvedAgent:
    config: AgentResponse
    prepared: PreparedToolset
    sandbox: ResolvedSandbox | None = None
```

The two gate sites (`runtime.py:187`, `:318`) change from `self.config.has_code_interpreter and sandbox_settings.enabled` to `self.sandbox is not None` (a binding to an existing sandbox row, resolved at request scope). Nothing downstream (streaming scope, runs worker, subagent compile) touches the DB or a global; triggers, Slack, and the durable runs worker inherit this for free.

Tool gating: `disabled` entries are dropped from the toolset; `needs_approval` joins the same HITL wiring MCP tools use (parent agent only, same subagent limitation as today).

**Session provenance caveat**: `connect_sandbox(id)` reconnects through whatever sandbox the agent is bound to *now*; if an admin swaps the binding mid-thread, old session ids fail and the tool already degrades gracefully ("create a new sandbox instead"). No cross-provider id namespacing in v1.

## 6. API surface & frontend

### 6.1 Endpoints

`app/sandbox/` grows the standard stack (`models/schemas/repository/service/router`); `SandboxService(BaseService[SandboxDB, SandboxRepository])`:

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `GET /sandboxes` | any user | active rows (id, name, description, provider, url) — consumed by the agent editor |
| `POST /sandboxes` | `require_admin` | discriminated create; config validated through the union; secret write-only |
| `GET /sandboxes/{id}` | `require_admin` | full config, secret omitted |
| `GET /sandboxes/{id}/secret-hint` | `require_admin` | masked hint, mirrors `oauth-secret-hint` |
| `PATCH /sandboxes/{id}` | `require_admin` | omitted secret = keep current |
| `POST /sandboxes/{id}/probe` | `require_admin` | connectivity check: create a throwaway session, `execute("true")`, report |
| `DELETE /sandboxes/{id}` | `require_admin` | refused (400) while agents are bound; `?detach_agents=true` (the dialog's explicit confirm) detaches from all agents then deletes. `GET /sandboxes/{id}/agents` feeds the dialog. Threads are never bound to sandboxes |

`GET /sandbox/status` is deleted; its only caller (`add-agent-tool-dialog.tsx`) switches to `GET /sandboxes` (enabled ⇔ non-empty).

### 6.2 Workspace admin page — `/sandboxes`

Sibling of the MCP servers page, shared DataTable (Petrol Mono kit):

```
SANDBOXES 3                                        + Add sandbox
┌──────────────┬─────────────┬───────────────────────────┬────────┐
│ NAME         │ PROVIDER    │ URL                       │ AGENTS │
├──────────────┼─────────────┼───────────────────────────┼────────┤
│ Python VM    │ OPENSANDBOX │ sbx.internal.example.com  │ 4      │
│ Data lab     │ CLOUD RUN   │ sbx-gw…run.app            │ 1      │
│ Daytona US   │ DAYTONA     │ app.daytona.io/api        │ 0      │
└──────────────┴─────────────┴───────────────────────────┴────────┘
```

### 6.3 Create/edit dialog — generic base + per-provider field spec

The three-part anatomy (§3.1) makes the dialog mostly generic. A small client-side spec per provider drives the rest:

```
┌─ Add sandbox ────────────────────────────────┐
│ Provider   [ OpenSandbox ▾ ]                 │   ← Select over SandboxProviderType
│ Name       [____________________]           │  ┐
│ URL        [____________________]           │  │ base fields — always rendered,
│ Secret     [•••••••••  (write-only)]        │  │ label/placeholder from the spec
│ Packages   [pandas, numpy]                  │  │ ("API key" vs "Gateway secret")
│ Timeout    [30 min]                         │  ┘
│ ── OpenSandbox options ─────────────────    │
│ Image      [python:3.12-slim]               │  ← extras group from the spec:
│ Volumes    [____________________]           │     one component per provider,
│ [x] Use server proxy                        │     fields mirror the config model
│                                  [ Create ] │
└──────────────────────────────────────────────┘
```

```ts
// web — per-provider spec; adding Daytona = one more entry
const SANDBOX_PROVIDER_SPECS = {
  opensandbox: { label: "OpenSandbox", secretLabel: "API key", secretRequired: false, Extras: OpenSandboxExtras },
  cloudrun:    { label: "Cloud Run",   secretLabel: "Gateway secret", secretRequired: true, Extras: CloudRunExtras },
  daytona:     { label: "Daytona",     secretLabel: "API key", secretRequired: true, defaultUrl: "https://app.daytona.io/api", Extras: DaytonaExtras },
} satisfies Record<SandboxProviderType, SandboxProviderSpec>;
```

Server-side validation (the union) remains the authority; the spec is presentation only. Edit mode: secret field empty with the stored hint as placeholder; leaving it empty keeps the current value. Delete blocked with "in use by N agents".

### 6.4 Agent editor — sandbox card inside TOOLS (unchanged from v1)

The static "Code execution" row (`agent-code-execution.tsx`) becomes a per-sandbox card with the exact MCP-card skeleton (`agent-mcp-server.tsx:199`): 26px glyph tile (`SquareTerminal` — no `icon_url`), name, provider pill (`OPENSANDBOX` / `CLOUD RUN` / `DAYTONA` in the status-pill recipe: `rounded-[4px] px-2 py-0.5 font-mono text-[9.5px]`), chevron expand → the 3 static tool rows with `ThreeStateToggle`, "Disable {name}" footer.

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

Add-tool dialog: the built-in `Switch` block becomes a `SANDBOXES` grid section (same heading/card recipes as the MCP grid); it hides once one sandbox is bound (one-per-agent) and when `GET /sandboxes` is empty.

Form state: extend the four canonical helpers in `agents/lib/agent-form.ts` (`defaultAgentForm`, `fromAgent`, `toPayload`, `isFormDirty`) with `sandboxes: AgentSandboxForm[]` (`{sandboxId, tools}`); `toPayload` inclusion drives dirtiness/UNSAVED; axios `PRESERVE_KEYS_FIELDS` already covers `tools`. `types/agents.ts` gains `Sandbox`, `AgentSandbox`, `Agent.sandboxes`; `hasCodeInterpreter` removed.

## 7. Migration — env as a one-shot input, then gone

One alembic revision:

1. Create `sandboxes` and `agent_sandboxes`.
2. **One-shot conversion**: instantiate today's `SandboxSettings` (env is present where `alembic upgrade head` runs); if `enabled`, insert one **normal, editable** `sandboxes` row from the env values (name `"OpenSandbox"` / `"Cloud Run"`, secret encrypted). No `source` column, no boot-time re-sync — after this migration the DB is the sole source of truth and the `SANDBOX_*` / `OPEN_SANDBOX_*` / `CLOUD_RUN_SANDBOX_*` env vars are dead (remove from `.env.example`; note in the release changelog).
3. For every agent with `has_code_interpreter = true`, insert an `agent_sandboxes` row pointing at that row. If no provider was configured, the flag was a no-op — dropped silently.
4. Drop `agents.has_code_interpreter`.

Fresh installs never set the env vars: the admin creates their first sandbox in the UI, exactly like their first MCP server. (Known small loss: a flag set to `true` on a deployment that never configured env produces no binding — the feature never worked there anyway.)

## 8. Rollout phases

1. **Backend core** — tables + one-shot migration, shared `app/utils/encryption.py`, typed config union + hydration, `BaseSandboxProvider` + registry + refactored opensandbox/cloudrun providers, `AgentSandboxService.set_for_agent` wired into `set_config`/`create_from_config`, `ResolvedAgent.sandbox` resolution, full `/sandboxes` CRUD + probe endpoints, drop `/sandbox/status`. Existing env-configured deployments upgrade seamlessly via the migration.
2. **Workspace admin UI** — `/sandboxes` DataTable page, create/edit dialog with the per-provider spec, secret hint UX, probe button, delete guard.
3. **Agent editor UI** — form-state plumbing, sandbox card in TOOLS, add-dialog SANDBOXES section, read mode, tool-status gating (disabled + HITL on `execute`).
4. **Daytona** — `DaytonaSandbox(BaseSandbox)` + `DaytonaProvider` + `DaytonaConfig` + registry/spec entries; the phase that proves §3.4's "adding a provider" checklist.

Phases 2 and 3 are independent once 1 lands; 4 is independent of both.

## 9. Open questions

- **Secret optionality**: opensandbox allows a keyless deployment today (`api_key: str | None`). Kept nullable; the per-provider validators own required-ness.
- **Subagents**: bindings stay per-agent (a supervisor's sandbox is not inherited) — same semantics as the old flag. Revisit alongside the known cloudrun subagent-persist gap.
- **Legacy API fields**: `POST /agents` / `PATCH` lose `has_code_interpreter` in phase 1 — pre-1.0 breaking is fine per release-please (`feat!` bumps minor), title the PR accordingly.
- **Daytona SDK details** (exact create/connect/exec signatures, snapshot semantics, auto-stop units) to be verified against the current SDK when phase 4 starts.
