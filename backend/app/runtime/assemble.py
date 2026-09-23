"""Stage 3 of executing a run: assemble the LangGraph runnable. Pure construction.

`assemble(resolved, live, output_schema=…)` takes what `resolve` read and what
`open_resources` opened and returns the compiled graph for one turn: the
parent's `create_agent` with its middleware stack, its subagents compiled into
`CompiledSubAgent`s for the `task` tool, the harness when a sandbox is bound.
No IO happens here — every handle arrives as an argument — which is what lets
`tests/runtime/test_harness_parity.py` pin the assembly to what
`create_deep_agent` builds without a database or a network.

`build_runnable` is the one construction path (parent or subagent, sandboxed
or not); `build_agent_middleware` the one middleware stack.
"""

from datetime import datetime

from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)

from app.runtime.harness import (
    HARNESS_CONFIG,
    harness_middleware,
    harness_system_prompt,
    harness_trailing_middleware,
)
from app.runtime.middleware.current_date import CurrentDateMiddleware
from app.runtime.middleware.structured_output import (
    FORMAT_TOOL,
    PROVIDER_FORMAT_MODES,
    DeferredStructuredOutputMiddleware,
)
from app.runtime.middleware.tool_errors import (
    RepairInvalidToolCallsMiddleware,
    ToolErrorMiddleware,
)
from app.runtime.resolve import ResolvedAgent, ResolvedRun
from app.runtime.resources import LiveResources
from app.runtime.settings import agent_settings
from app.runtime.toolset import PreparedToolset, sanitize_tool_name
from app.skills.middleware import skills_read_middleware
from app.skills.runtime import SkillsBackend


def build_runnable(
    *,
    model,
    tools,
    system_prompt,
    sandbox_backend=None,
    skills: SkillsBackend | None = None,
    base_middleware=(),
    subagents=None,
    checkpointer=None,
    output_schema: dict | None = None,
    format_mode: str = FORMAT_TOOL,
):
    """Build a LangGraph runnable. One construction path, one middleware list.

    Every agent — parent or subagent, sandboxed or not — is a ``create_agent``
    with an explicit middleware stack. A sandbox adds deepagents' harness
    (todos, skills, filesystem, the ``task`` tool, summarization, the tool-call
    patcher and prompt caching) and appends the harness prompt to the agent's
    instructions; ``app/runtime/harness.py`` assembles that bundle and
    ``tests/runtime/test_harness_parity.py`` pins it to what ``create_deep_agent``
    builds. Nothing else forks on the sandbox.

    ``sandbox_backend`` is a *live* sandbox — the runtime connects it before
    the graph is built (``Agent._setup``); the model never creates or
    reconnects one. ``skills`` is the run's read-only ``SkillsBackend`` (None
    when the graph has no skills, which means no middleware and no prompt
    fragment, as in ``create_deep_agent``): the skill index is always read
    from it, and an agent without a sandbox also gets ``ls`` / ``read_file``
    over it — its only filesystem, and no process anywhere.

    ``base_middleware`` is the caller's own stack — the parent passes
    ``build_parent_middleware``'s list; subagents pass their own retry/limit/
    repair/date stack (see ``ResolvedAgent.compile``). It sits where deepagents
    puts caller middleware: after the harness, before prompt caching.

    ``DeferredStructuredOutputMiddleware`` is appended whenever an
    ``output_schema`` is given (it keeps the schema off the tool-calling loop
    and applies it on one final formatting turn). ``ToolErrorMiddleware`` is
    always appended: without it the ToolNode has no tool-call wrapper, and
    langgraph's default handler re-raises any exception that isn't a
    ``ToolInvocationError`` — an MCP transport failure in a tool (or in a
    subagent reached through ``task``) would then kill the whole run instead of
    feeding back to the model as an error ToolMessage.

    ``subagents`` (already-compiled ``CompiledSubAgent`` runnables) wire in
    through ``SubAgentMiddleware`` either way: the harness builds it, and
    without a sandbox it is added here over the in-state filesystem.

    Every graph is compiled with deepagents' ``DeepAgentState``: its
    ``messages`` channel is a ``DeltaChannel``, so a checkpoint stores the
    step's writes rather than the whole conversation (O(N) growth over a
    thread instead of O(N²)). deepagents only does this for the deep agent;
    plain agents and subagents have the same long threads, so they get it
    too. The price is that ``channel_values["messages"]`` is no longer
    readable raw — every out-of-request reader goes through
    ``app.runtime.checkpoints.get_checkpoint_state``.
    """
    tools = list(tools)
    harness: list = []

    if sandbox_backend is not None:
        harness += harness_middleware(
            model=model,
            tools=tools,
            backend=sandbox_backend,
            subagents=subagents,
            skills=skills,
        )
        system_prompt = harness_system_prompt(model, system_prompt)
        # The harness brings its own PatchToolCallsMiddleware and langchain
        # asserts against duplicates, so the caller's copy is dropped.
        base_middleware = [
            m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
        ]
    elif skills is not None:
        harness += skills_read_middleware(skills)

    middleware = [*harness, *base_middleware]
    if sandbox_backend is None and subagents:
        # On the far side of the caller's stack, where the plain path has
        # always put it — the harness wires its own SubAgentMiddleware *before*
        # the caller's, because that is where deepagents puts it. Since
        # deepagents 0.7 the middleware injects no system-prompt fragment of
        # its own (the `task` tool description carries the agent list), so the
        # position only orders hooks now.
        middleware.append(
            SubAgentMiddleware(backend=StateBackend(), subagents=subagents)
        )
    if output_schema is not None:
        middleware.append(DeferredStructuredOutputMiddleware(format_mode))
    middleware.append(ToolErrorMiddleware())
    if sandbox_backend is not None:
        middleware += harness_trailing_middleware(model)

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
        response_format=output_schema,
        state_schema=DeepAgentState,
    )
    # deepagents binds this onto every graph it builds; keep it on the sandbox
    # path so a subagent invoked by `task` keeps the recursion budget it had.
    return agent.with_config(HARNESS_CONFIG) if sandbox_backend is not None else agent


def build_agent_middleware(
    created_at: datetime,
    *,
    recursion_limit: int,
    interrupt_on: dict[str, bool] | None = None,
) -> list:
    """The middleware stack every agent gets, parent or subagent.

    Order is load-bearing. PatchToolCallsMiddleware runs first so that any
    dangling tool_calls left by a previous aborted turn (recursion limit,
    cancelled stream, etc.) get synthetic ToolMessage responses before the model
    sees them. ModelRetryMiddleware is listed early so a retry re-runs the whole
    inner pipeline (date stamp, deferred formatting); it retries transient model
    failures (rate limits, timeouts, connection drops — classified via
    ``ModelError.is_retryable``) and, when retries are exhausted, persists the
    failure as an AIMessage so the turn ends visibly instead of crashing.
    Non-retryable errors (e.g. provider 400s) re-raise immediately and surface
    through the run record. RepairInvalidToolCallsMiddleware is placed *before*
    HITL so it runs *after* it (after_model hooks execute last-to-first): HITL
    must see only the genuine tool_calls and gate those, while the malformed
    calls stay in invalid_tool_calls (invisible to HITL) until Repair promotes
    them into tool_calls answered by error ToolMessages.

    ``interrupt_on`` — a mapping (even an empty one) means this agent runs
    against a checkpointer, so it can be interrupted for approval and can have
    dangling tool calls persisted by an aborted turn; ``None`` drops both the
    approval gate and the patcher. Parent *and* subagents are checkpointed:
    the deepagents ``task`` tool spreads the parent's ``configurable`` into the
    subagent, which carries the checkpointer and the ``tools:<task-id>``
    namespace, so a subagent's interrupt propagates to the root checkpoint
    (with an id that encodes its namespace) and an id-keyed resume routes back
    into it — see ``app/runtime/hitl.py``. Only tests and the structured-output
    formatting turn pass ``None``.

    ``recursion_limit`` — the tool budget is sized to end the run gracefully
    one step before the graph's own recursion limit trips. A subagent runs
    under the same limit as its parent: the ``task`` tool invokes it inside
    the parent's tool node, and langgraph seeds the nested run from that
    ambient config, ``recursion_limit`` included (on the sandbox path the
    graph's bound ``HARNESS_CONFIG`` then wins the merge, so the tool budget
    is the limit that actually ends the run).
    """
    checkpointed = interrupt_on is not None
    return [
        *([PatchToolCallsMiddleware()] if checkpointed else []),
        ModelRetryMiddleware(),
        ToolCallLimitMiddleware(
            run_limit=(recursion_limit - 1) // 2, exit_behavior="end"
        ),
        RepairInvalidToolCallsMiddleware(),
        *(
            [
                HumanInTheLoopMiddleware(
                    interrupt_on=interrupt_on,
                    description_prefix="Tool execution pending approval",
                )
            ]
            if checkpointed
            else []
        ),
        CurrentDateMiddleware(created_at),
    ]


def build_parent_middleware(created_at: datetime, prepared: PreparedToolset) -> list:
    """The parent agent's stack: checkpointed, under our own recursion limit."""
    return build_agent_middleware(
        created_at,
        recursion_limit=agent_settings.recursion_limit,
        interrupt_on=prepared.interrupt_on,
    )


def compile_subagent(
    agent: ResolvedAgent,
    *,
    model,
    tools: list,
    created_at: datetime,
    sandbox_backend=None,
    skills: SkillsBackend | None = None,
) -> CompiledSubAgent:
    """Compile a subagent into the `CompiledSubAgent` the `task` tool runs.

    ``created_at`` is the thread's creation date, stamped onto the
    subagent's system prompt by ``CurrentDateMiddleware``.
    ``sandbox_backend`` is the run's one live sandbox, handed over when
    this subagent is bound to a sandbox; ``skills`` the run's shared set.

    A subagent gets its own copy of the shared middleware stack rather than
    inheriting the parent's: the deepagents ``task`` tool invokes it as a
    nested subgraph (parent middleware doesn't propagate; the run config —
    checkpointer, namespace, recursion limit — does) and reports back only
    the last AI message's text, so a subagent that exits its loop silently
    (invalid tool-call JSON) would return an empty ToolMessage and one that
    blows the recursion limit would discard its progress. Its own
    ``interrupt_on`` gates its tools: the interrupt surfaces on the root
    checkpoint and the web client / Slack approve it like a parent's
    (issue #301).
    """
    # A subagent bound to a sandbox shares the run's one live sandbox, so
    # the parent's turn-end persist covers what it wrote (issue #302).
    runnable = build_runnable(
        model=model,
        tools=tools,
        system_prompt=agent.config.instructions or "",
        sandbox_backend=sandbox_backend if agent.sandbox else None,
        skills=skills,
        base_middleware=build_agent_middleware(
            created_at,
            recursion_limit=agent_settings.recursion_limit,
            interrupt_on=agent.prepared.interrupt_on,
        ),
    )
    return CompiledSubAgent(
        name=sanitize_tool_name(agent.config.name),
        description=f"{agent.config.name}: {agent.config.description or agent.config.name}",
        runnable=runnable,
    )


def assemble(
    resolved: ResolvedRun, live: LiveResources, *, output_schema: dict | None = None
):
    """The turn's graph: the parent over its live tools, with its subagents
    compiled in, against this turn's checkpointer.

    `output_schema` is a raw JSON Schema dict passed to langchain as
    `response_format`. DeferredStructuredOutputMiddleware keeps the schema
    off the tool-calling loop and applies it on one final formatting turn;
    the parsed result surfaces in the run state under `structured_response`.
    """
    created_at = resolved.thread.created_at
    # Read-only and shared by every agent of the graph; None means no
    # skills middleware and no prompt fragment at all.
    skills = SkillsBackend(resolved.skills) if resolved.skills else None
    compiled = (
        [
            compile_subagent(
                sub,
                model=resolved.model,
                tools=live.tools_for(sub),
                created_at=created_at,
                sandbox_backend=live.sandbox_backend_for(sub),
                skills=skills,
            )
            for sub in resolved.subagents
        ]
        if resolved.subagents
        else None
    )
    return build_runnable(
        model=resolved.model,
        tools=live.tools_for(resolved.agent),
        system_prompt=resolved.agent.config.instructions or "",
        sandbox_backend=live.sandbox_backend_for(resolved.agent),
        skills=skills,
        base_middleware=build_parent_middleware(created_at, resolved.agent.prepared),
        subagents=compiled,
        checkpointer=live.checkpointer,
        output_schema=output_schema,
        format_mode=PROVIDER_FORMAT_MODES.get(resolved.provider, FORMAT_TOOL),
    )
