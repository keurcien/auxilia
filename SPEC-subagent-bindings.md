# Spec: Subagent Bindings

## Goal

Allow agents to have subagents (one level deep). When an agent has subagents, it becomes a coordinator that uses Deep Agents' `SubAgentMiddleware` to delegate tasks. Only workspace admins can bind/unbind subagents.

## Data Model

### New table: `agent_subagent_bindings`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `coordinator_id` | UUID | FK → agents.id, NOT NULL |
| `subagent_id` | UUID | FK → agents.id, NOT NULL |
| `created_at` | DateTime(tz) | server_default=now() |
| `updated_at` | DateTime(tz) | server_default=now(), onupdate=now() |

**Unique constraint**: `(coordinator_id, subagent_id)`

No extra config columns — the subagent's own name, description, instructions, and MCP tools define its behavior.

### One-level-deep constraint (service layer)

When creating a binding (A → B):
1. `A != B` (no self-reference)
2. B has no children (B is not already a coordinator)
3. A is not a child of anyone (A is not already a subagent)

When archiving an agent:
- Also delete its subagent bindings (both as coordinator and as subagent) — handled by cascade or explicit cleanup.

### Models

```python
# DB model
class AgentSubagentBindingDB(SQLModel, table=True):
    __tablename__ = "agent_subagent_bindings"
    __table_args__ = (UniqueConstraint("coordinator_id", "subagent_id"),)
    id: UUID
    coordinator_id: UUID  # FK agents.id
    subagent_id: UUID     # FK agents.id
    created_at: datetime
    updated_at: datetime

# Lightweight read model for embedding in AgentRead
class SubagentRead(SQLModel):
    id: str          # agent ID
    name: str
    emoji: str | None
    description: str | None

# Response model for binding
class AgentSubagentBindingRead(SQLModel):
    id: UUID
    coordinator_id: UUID
    subagent_id: UUID
    created_at: datetime
    updated_at: datetime
```

### AgentRead extension

```python
class AgentRead(SQLModel):
    # ... existing fields ...
    subagents: list[SubagentRead] | None = None
    coordinator_of: SubagentCoordinatorInfo | None = None  # set when this agent is used as subagent
```

`is_subagent` is a computed boolean — `True` when this agent is bound as a subagent in any coordinator. The frontend uses it to show an info banner instead of the "Add Subagent" button.

## API Endpoints

All subagent endpoints require `require_admin`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/agents/{agent_id}/subagents/{subagent_id}` | Bind subagent |
| DELETE | `/agents/{agent_id}/subagents/{subagent_id}` | Unbind subagent |

POST returns `AgentSubagentBindingRead` (201).
DELETE returns 204.

Validation errors return 400 with descriptive message:
- "Cannot add an agent as its own subagent"
- "This agent already has subagents and cannot be used as a subagent"
- "This agent is already used as a subagent and cannot have subagents"

## Runtime Changes

### `AgentRuntime.stream_langgraph()` — use `create_deep_agent` when subagents exist

In `stream_langgraph()`, after building tools and middlewares:

```python
if self.config.subagents:
    # Build CompiledSubAgent specs
    compiled_subagents = []
    for sub_config in subagent_configs:
        sub_agent = create_agent(
            model=chat_model,  # same model as coordinator
            tools=sub_tools,
            system_prompt=SystemMessage(content=[{"type": "text", "text": sub_config.instructions}]),
            middleware=sub_middlewares,
        )
        compiled_subagents.append(CompiledSubAgent(
            name=sub_config.name,
            description=sub_config.description or sub_config.name,
            runnable=sub_agent,
        ))

    agent = create_deep_agent(
        model=chat_model,
        tools=tools,
        system_prompt=SystemMessage(content=[system_prompt]),
        checkpointer=checkpointer,
        middleware=middlewares,
        subagents=compiled_subagents,
    )
else:
    agent = create_agent(...)  # existing path
```

### Subagent tool loading

Each subagent needs its own MCP tools loaded. This means `AgentRuntime.initialize()` must also load subagent configs and their tools.

Add to `AgentRuntime`:
- `self.subagent_runtimes: list[SubagentRuntimeConfig]` — lightweight struct holding each subagent's config + loaded tools
- Load subagent tools in parallel during `initialize()`

### `stream()` (AI SDK adapter) — no changes needed initially

The AI SDK stream path uses `create_agent` and doesn't support subgraph streaming. Subagent support is only for the LangGraph native stream path (`stream_langgraph`).

## Frontend Changes

### Types

```typescript
// types/agents.ts
export interface SubagentInfo {
  id: string;
  name: string;
  emoji?: string | null;
  description?: string | null;
}

export interface SubagentCoordinatorInfo {
  id: string;
  name: string;
  emoji?: string | null;
}

export interface Agent {
  // ... existing fields ...
  subagents: SubagentInfo[];
  coordinatorOf?: SubagentCoordinatorInfo | null;
}
```

### Agent Editor — add subagent section

In `agent-editor.tsx`, below the `AgentMCPServerList` in the right panel, add `AgentSubagentList`.

If `agent.coordinatorOf` is set, show an info banner instead:
> "This agent is used as a subagent in **[CoordinatorName]** and cannot have subagents of its own."

### New component: `agent-subagent-list.tsx`

Located at `web/src/app/(protected)/agents/[id]/components/agent-subagent-list.tsx`.

Pattern mirrors `agent-mcp-server-list.tsx`:
- Shows bound subagents as cards (emoji + name + description + remove button)
- "Add Subagent" button opens dialog
- Only visible to workspace admins (check `user.role === "admin"`)

### New component: `add-agent-subagent-dialog.tsx`

Located at `web/src/app/(protected)/agents/[id]/components/add-agent-subagent-dialog.tsx`.

Pattern mirrors `add-agent-mcp-server-dialog.tsx`:
- Lists eligible agents (not self, not archived, not already bound, not coordinators)
- Agents that are already subagents elsewhere are shown grayed out with reason: "Used as subagent in [Name]"
- Agents that already have subagents are shown grayed out with reason: "Has subagents"

Eligible agents are fetched from `GET /agents/` and filtered client-side.

### Existing component: `agent-subagent-card.tsx`

Simple card showing: emoji, name, description, remove (X) button.
Remove calls `DELETE /agents/{agentId}/subagents/{subagentId}`.

## Service layer changes

### `AgentService.get_agent()` — load subagents

Join `agent_subagent_bindings` and resolve subagent agent rows to build `subagents: list[SubagentRead]`.

Also check if this agent is used as a subagent (query where `subagent_id = agent_id`) and populate `coordinator_of`.

### `AgentService.list_agents()` — load subagents for all agents

Similar join. The list query already joins MCP bindings; add a second pass or subquery for subagent bindings.

### `AgentService.delete_agent()` — cleanup bindings

When archiving an agent, also delete all `agent_subagent_bindings` where it appears as coordinator or subagent.

### New methods

```python
async def create_subagent_binding(self, coordinator_id: UUID, subagent_id: UUID) -> AgentSubagentBindingDB
async def delete_subagent_binding(self, coordinator_id: UUID, subagent_id: UUID) -> None
```

### Repository additions

```python
async def get_subagent_binding(self, coordinator_id: UUID, subagent_id: UUID) -> AgentSubagentBindingDB | None
async def get_subagent_bindings(self, coordinator_id: UUID) -> list[AgentSubagentBindingDB]
async def get_coordinator_binding(self, subagent_id: UUID) -> AgentSubagentBindingDB | None
async def has_subagents(self, agent_id: UUID) -> bool
async def is_subagent(self, agent_id: UUID) -> bool
async def create_subagent_binding(self, coordinator_id: UUID, subagent_id: UUID) -> AgentSubagentBindingDB
async def delete_subagent_binding(self, binding: AgentSubagentBindingDB) -> None
async def delete_all_subagent_bindings(self, agent_id: UUID) -> None
```

## Implementation Order

1. Migration: create `agent_subagent_bindings` table
2. Backend models: `AgentSubagentBindingDB`, `SubagentRead`, `SubagentCoordinatorInfo`, `AgentSubagentBindingRead`
3. Repository: subagent binding CRUD + constraint checks
4. Service: `create_subagent_binding`, `delete_subagent_binding`, update `get_agent`/`list_agents`/`delete_agent`
5. Router: POST/DELETE endpoints with `require_admin`
6. Runtime: `create_deep_agent` path in `stream_langgraph()` with `CompiledSubAgent`
7. Frontend types: extend `Agent`, add `SubagentInfo`
8. Frontend components: `agent-subagent-list.tsx`, `add-agent-subagent-dialog.tsx`
9. Frontend editor: wire into `agent-editor.tsx`

## Edge Cases

- **Archived agents**: An archived agent should not be available as a subagent. Filter in dialog.
- **Agent deletion cascade**: When archiving a coordinator, remove all its subagent bindings. When archiving a subagent, remove its binding from the coordinator.
- **Permissions**: Subagent binding requires workspace admin. The subagent's own tools/permissions still apply when it runs.
- **Duplicate binding**: POST is idempotent — if binding already exists, return it.
- **Empty subagents**: Agent with `subagents: []` uses `create_agent` (standard path). Only agents with `len(subagents) > 0` use `create_deep_agent`.
