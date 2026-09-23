"""`assemble` — what the graph is built *with* (middleware lists, response
format, state schema). `test_agent_behaviour.py` proves what the built graph
does; `test_harness_parity.py` pins the sandbox assembly to `create_deep_agent`.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import ModelRetryMiddleware, ToolCallLimitMiddleware

from app.agents.run_spec import AgentSpec
from app.runtime.assemble import assemble, build_parent_middleware, compile_subagent
from app.runtime.middleware.current_date import CurrentDateMiddleware
from app.runtime.middleware.structured_output import (
    FORMAT_JSON_OBJECT,
    FORMAT_PROVIDER_NATIVE,
    FORMAT_TOOL,
    DeferredStructuredOutputMiddleware,
)
from app.runtime.middleware.tool_errors import (
    RepairInvalidToolCallsMiddleware,
    ToolErrorMiddleware,
)
from app.runtime.resolve import ResolvedAgent, ResolvedRun, ResolvedSandbox
from app.runtime.resources import LiveResources
from app.runtime.settings import agent_settings
from app.runtime.toolset import PreparedToolset
from app.sandbox.provider import SandboxSession
from tests.runtime.scripted_model import ScriptedChatModel
from tests.sandbox.stub_sandbox import StubSandbox


CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _prepared(interrupt_on: dict | None = None) -> PreparedToolset:
    return PreparedToolset(
        connections={},
        tool_settings={},
        server_id_by_name={},
        interrupt_on=interrupt_on or {},
        apply_ui=False,
    )


def _spec(instructions: str = "You are a test agent") -> AgentSpec:
    return AgentSpec(
        id=uuid4(),
        name="Tester",
        instructions=instructions,
        description="a test agent",
        mcp_servers=[],
        sandbox=None,
    )


def _resolved_agent(*, sandbox: bool = False) -> ResolvedAgent:
    agent = ResolvedAgent(config=_spec(), prepared=_prepared())
    if sandbox:
        agent.sandbox = ResolvedSandbox(provider=MagicMock(), tools=None)
    return agent


def _live(agent: ResolvedAgent, *, sandbox: bool = False, tools=()) -> LiveResources:
    live = LiveResources(
        checkpointer=None,
        toolsets={agent.config.id: MagicMock(all=list(tools))},
    )
    if sandbox:
        # `open_resources` opens the run's sandbox before the graph is built;
        # stand in for that here so `assemble` sees a live backend.
        live.sandbox = SandboxSession(backend=StubSandbox(), sandbox_id="sbx-1")
    return live


def _assemble(
    *,
    sandbox: bool = False,
    provider: str | None = None,
    model=None,
    skills=(),
    output_schema: dict | None = None,
):
    agent = _resolved_agent(sandbox=sandbox)
    resolved = ResolvedRun(
        thread=MagicMock(created_at=CREATED_AT),
        agent=agent,
        subagents=[],
        model=model if model is not None else MagicMock(),
        provider=provider,
        skills=list(skills),
    )
    return assemble(
        resolved, _live(agent, sandbox=sandbox), output_schema=output_schema
    )


SCHEMA = {
    "title": "answer",
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
}


@patch("app.runtime.assemble.create_agent")
def test_assemble_forwards_output_schema(mock_create_agent):
    """An output schema is passed to create_agent as response_format."""
    _assemble(output_schema=SCHEMA)

    assert mock_create_agent.call_args.kwargs["response_format"] == SCHEMA
    # The schema must be deferred off the tool-calling loop, otherwise the
    # model skips tools and fabricates values to satisfy the constraint.
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert any(isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware)


@patch("app.runtime.assemble.create_agent")
def test_assemble_routes_provider_to_format_mode(mock_create_agent):
    """The formatting middleware's format_mode is resolved per provider (and must
    reach the non-sandbox create_agent middleware, not just the sandbox one):
    Meta rejects a forced tool call but takes json_schema (provider_native);
    DeepSeek thinking rejects both, so it uses json_object; everyone else uses
    the default forced tool call."""

    def format_mode_for(provider: str) -> str:
        # `provider` is resolved once by `resolve` (via ModelService) and
        # carried on the ResolvedRun — `assemble` reads it from there.
        _assemble(provider=provider, output_schema=SCHEMA)
        middleware = mock_create_agent.call_args.kwargs["middleware"]
        deferred = next(
            m for m in middleware if isinstance(m, DeferredStructuredOutputMiddleware)
        )
        return deferred.format_mode

    assert format_mode_for("meta") == FORMAT_PROVIDER_NATIVE
    assert format_mode_for("deepseek") == FORMAT_JSON_OBJECT
    assert format_mode_for("openai") == FORMAT_TOOL


@patch("app.runtime.assemble.create_agent")
def test_assemble_without_output_schema(mock_create_agent):
    """Without an output schema, response_format stays None."""
    _assemble()

    assert mock_create_agent.call_args.kwargs["response_format"] is None
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert not any(
        isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware
    )


@patch("app.runtime.assemble.create_agent")
def test_assemble_compiles_with_deep_agent_state(mock_create_agent):
    """Every graph — sandbox or not — carries deepagents' `DeltaChannel`
    messages state, so checkpoints grow linearly with the thread."""
    _assemble()

    assert mock_create_agent.call_args.kwargs["state_schema"] is DeepAgentState


@patch("app.runtime.assemble.create_agent")
def test_assemble_appends_tool_error_middleware(mock_create_agent):
    """The non-sandbox path must also contain tool errors: without a
    wrap_tool_call middleware the ToolNode has no wrapper and langgraph's
    default handler re-raises anything that isn't a ToolInvocationError — an
    MCP transport failure (in a tool, or in a subagent reached through `task`)
    then crashes the whole run instead of feeding back to the model."""
    _assemble()

    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert isinstance(middleware[-1], ToolErrorMiddleware)


@patch("app.runtime.assemble.create_agent")
def test_assemble_sandbox_uses_the_same_create_agent_path(mock_create_agent):
    """A sandbox no longer forks the construction path: it adds deepagents'
    harness middleware to the same `create_agent` call. The parent stack's
    PatchToolCallsMiddleware is dropped in favour of the harness's one
    (langchain asserts against duplicates), and prompt caching closes the
    stack.

    `tests/runtime/test_harness_parity.py` pins the assembly to what
    `create_deep_agent` built, middleware for middleware; this only checks that
    the sandbox reaches it."""
    # The harness sizes its summarization thresholds off the model, so this
    # path needs a real BaseChatModel rather than a mock.
    _assemble(sandbox=True, model=ScriptedChatModel(script=[]))

    middleware = mock_create_agent.call_args.kwargs["middleware"]
    names = [type(m).__name__ for m in middleware]
    assert names.count("PatchToolCallsMiddleware") == 1
    assert "FilesystemMiddleware" in names
    assert names[-1] == "AnthropicPromptCachingMiddleware"
    assert "ToolErrorMiddleware" in names


@patch("app.runtime.assemble.create_agent")
def test_compile_subagent_middleware_stack(mock_create_agent):
    """Subagents need their own repair/limit/retry middleware: the deepagents
    task tool invokes them as a nested graph (parent middleware doesn't
    propagate) and reports back only the last message's text — a subagent that
    exits its loop silently on invalid tool-call JSON would return an empty
    ToolMessage to the parent, and one that blows the recursion limit would
    discard its progress."""
    helper = ResolvedAgent(
        config=AgentSpec(
            id=uuid4(),
            name="Helper",
            instructions="You are a helper",
            description="helps",
            mcp_servers=[],
            sandbox=None,
        ),
        prepared=_prepared(),
    )

    compile_subagent(helper, model=MagicMock(), tools=[], created_at=CREATED_AT)

    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert any(isinstance(m, ModelRetryMiddleware) for m in middleware)
    assert any(isinstance(m, RepairInvalidToolCallsMiddleware) for m in middleware)
    assert any(isinstance(m, CurrentDateMiddleware) for m in middleware)
    assert isinstance(middleware[-1], ToolErrorMiddleware)
    # A subagent inherits the parent's recursion_limit through the task tool's
    # ambient config, so its tool budget is sized like the parent's.
    limiter = next(m for m in middleware if isinstance(m, ToolCallLimitMiddleware))
    assert limiter.exit_behavior == "end"
    assert limiter.run_limit == (agent_settings.recursion_limit - 1) // 2


def test_parent_middleware_stack():
    """ModelRetryMiddleware retries transient model failures; Repair stays
    listed before HITL so it executes after it (after_model hooks run
    last-to-first), keeping malformed calls invisible to the approval gate."""
    middleware = build_parent_middleware(CREATED_AT, _prepared())

    types = [type(m).__name__ for m in middleware]
    assert any(isinstance(m, ModelRetryMiddleware) for m in middleware)
    assert types.index("RepairInvalidToolCallsMiddleware") < types.index(
        "HumanInTheLoopMiddleware"
    )
