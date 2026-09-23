"""Stage 1 of executing a run: read everything the graph needs from the database.

`resolve(thread, spec, db) -> ResolvedRun` binds the thread's model, the
parent agent and its subagents (each with a `PreparedToolset`, its MCP
connection specs and interrupt map), the sandbox providers and the run's
skill set. Reads only — no network, no writes. What comes out is safe to carry
past the session's end: the next stage (`resources.open_resources`) is the
one that opens connections.

A resume (a HITL approval) resolves exactly as a first run does — there is
no per-thread copy of anything to reuse.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.run_spec import AgentSpec, RunSpec
from app.integrations.langfuse.callback import get_langfuse_callback_handler
from app.model_providers.catalog import ChatModelFactory
from app.model_providers.service import ModelService
from app.runtime.toolset import MCPResolutionScope, PreparedToolset, Toolset
from app.sandbox.provider import BaseSandboxProvider, build_provider
from app.skills.runtime import resolve_run_skills
from app.skills.schemas import SkillBundle
from app.threads.models import ThreadDB


@dataclass
class ResolvedSandbox:
    """An agent's sandbox binding, resolved to a ready provider: the row is
    loaded and its credential decrypted at request scope, so the streaming
    scope (and subagent compile) never touch the DB or a global."""

    provider: BaseSandboxProvider
    tools: dict | None
    # The sandbox row this provider was built from: the thread stores it
    # alongside the sandbox id, so a later run can tell whether the id it
    # remembers was issued by *this* sandbox or a previous binding.
    row_id: UUID | None = None


@dataclass
class ResolvedAgent:
    """One graph member — the parent or a subagent — with its prepared toolset.

    `prepared` is the build-time half of the toolset (all DB work); the live
    half, tools bound to open MCP connections, is opened per run by
    `resources.open_resources` and looked up by `config.id`.
    """

    config: AgentSpec
    prepared: PreparedToolset
    sandbox: ResolvedSandbox | None = None

    @classmethod
    async def resolve(
        cls,
        spec: AgentSpec,
        db: AsyncSession,
        user_id: str,
        *,
        is_parent: bool = False,
        scope: MCPResolutionScope | None = None,
    ) -> "ResolvedAgent":
        """Bind one agent's spec to a prepared toolset.

        Takes an already-read `AgentSpec` rather than an id: the whole graph
        comes from a single `get_run_spec`, so resolving a subagent costs no
        further agent queries (design review §2.2). It also keeps the runtime
        off `AgentService`/`AgentResponse` — the run path has no business
        depending on API response assembly.

        `scope` carries the graph's MCP server rows, read once by `resolve`
        for the parent and every subagent together.
        """
        prepared = await Toolset.prepare(
            spec.mcp_servers, db, user_id, apply_ui=is_parent, scope=scope
        )
        return cls(config=spec, prepared=prepared, sandbox=cls._resolve_sandbox(spec))

    @staticmethod
    def _resolve_sandbox(spec: AgentSpec) -> ResolvedSandbox | None:
        if spec.sandbox is None:
            return None
        # A row that no longer validates (e.g. secret cleared) raises
        # `SandboxUnavailableError` and fails the run — the pre-run gate
        # reports the same, so this only covers a change made in between.
        # Silently running without code execution would be worse.
        provider = build_provider(spec.sandbox.row)
        return ResolvedSandbox(
            provider=provider,
            tools=spec.sandbox.tools,
            row_id=spec.sandbox.row.id,
        )


@dataclass
class ResolvedRun:
    """Everything a run needs that can be read up front.

    `callbacks` are the tracing handlers for the graph config; `skills` is
    the one set the whole graph shares, frozen for this run.
    """

    thread: ThreadDB
    agent: ResolvedAgent
    subagents: list[ResolvedAgent]
    model: object
    provider: str | None = None
    skills: list[SkillBundle] = field(default_factory=list)
    callbacks: list = field(default_factory=list)

    @property
    def members(self) -> list[ResolvedAgent]:
        """The graph's agents, parent first."""
        return [self.agent, *self.subagents]

    @property
    def metadata(self) -> dict:
        return {
            "user_id": self.thread.user_id,
            "thread_id": self.thread.id,
            "agent_id": self.thread.agent_id,
            "langfuse_session_id": self.thread.id,
        }


async def resolve(thread: ThreadDB, spec: RunSpec, db: AsyncSession) -> ResolvedRun:
    """Bind the thread's graph to its model, toolsets, sandboxes and skills.

    `spec` is the graph read the caller already holds (the worker reads it
    for the OAuth net first) — one `get_run_spec` per run, no re-read here.
    """
    user_id = str(thread.user_id)

    # Every MCP server the graph touches, in one query — the parent's and
    # each subagent's (design review §2.2 / P2-6).
    scope = await MCPResolutionScope.build(spec.all_mcp_bindings, db, user_id)
    agent = await ResolvedAgent.resolve(
        spec.agent, db, user_id, is_parent=True, scope=scope
    )

    # The model resolution — provider, id, key, clamped effort — doubles as
    # the last availability check before the graph is built: it covers the
    # race where the model is disabled between enqueue and worker pickup.
    resolved_model = await ModelService(db).ensure_available(
        thread.model_id, reasoning_effort=thread.reasoning_effort
    )
    model = ChatModelFactory().create(
        resolved_model.provider,
        resolved_model.model_id,
        resolved_model.api_key,
        reasoning_effort=resolved_model.reasoning_effort,
    )

    # Still sequential, and deliberately so: these share one AsyncSession,
    # which is not concurrency-safe. It no longer costs anything to be —
    # `get_run_spec` read the agent rows and `scope` the MCP ones, so each
    # resolve is Redis/CPU work over rows already in hand.
    subagents = [
        await ResolvedAgent.resolve(sub, db, user_id, scope=scope)
        for sub in spec.subagents
    ]

    # One skill set per graph: every agent lists, reads and runs the union
    # of what the supervisor and its subagents have enabled.
    skills = await resolve_run_skills(db, spec.all_agent_ids)

    handler = get_langfuse_callback_handler()
    return ResolvedRun(
        thread=thread,
        agent=agent,
        subagents=subagents,
        model=model,
        provider=resolved_model.provider,
        skills=list(skills),
        callbacks=[handler] if handler is not None else [],
    )
