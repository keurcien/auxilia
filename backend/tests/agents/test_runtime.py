from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from deepagents.graph import DeepAgentState
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from langchain.agents.middleware import ModelRetryMiddleware, ToolCallLimitMiddleware

from app.agents.current_date import CurrentDateMiddleware
from app.agents.runtime import (
    Agent,
    ResolvedAgent,
    build_parent_middleware,
)
from app.agents.settings import agent_settings
from app.agents.structured_output import (
    FORMAT_JSON_OBJECT,
    FORMAT_PROVIDER_NATIVE,
    FORMAT_TOOL,
    DeferredStructuredOutputMiddleware,
)
from app.agents.tool_errors import RepairInvalidToolCallsMiddleware, ToolErrorMiddleware
from app.sandbox.provider import SandboxSession
from tests.agents.scripted_model import ScriptedChatModel
from tests.sandbox.stub_sandbox import StubSandbox


def _build_agent(
    *,
    sandbox: bool = False,
    middleware=None,
    provider: str | None = None,
    model=None,
) -> Agent:
    resolved = MagicMock()
    resolved.sandbox = MagicMock() if sandbox else None
    resolved.config.instructions = "You are a test agent"
    resolved.live.all = []
    resolved.skills = {"entries": []}
    agent = Agent(
        thread=MagicMock(),
        agent=resolved,
        model=model if model is not None else MagicMock(),
        middleware=middleware if middleware is not None else [],
        callbacks=[],
        subagents=[],
        provider=provider,
    )
    if sandbox:
        # `_setup` connects the sandbox before building; stand in for it.
        backend = StubSandbox()
        agent._sandbox = SandboxSession(backend=backend, sandbox_id=backend.id)
    return agent


@patch("app.agents.runtime.create_agent")
def test_build_agent_forwards_output_schema(mock_create_agent):
    """An output schema is passed to create_agent as response_format."""
    agent = _build_agent()
    schema = {
        "title": "answer",
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }

    agent._build_agent(checkpointer=None, output_schema=schema)

    assert mock_create_agent.call_args.kwargs["response_format"] == schema
    # The schema must be deferred off the tool-calling loop, otherwise the
    # model skips tools and fabricates values to satisfy the constraint.
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert any(isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware)


@patch("app.agents.runtime.create_agent")
def test_build_agent_routes_provider_to_format_mode(mock_create_agent):
    """The formatting middleware's format_mode is resolved per provider (and must
    reach the non-sandbox create_agent middleware, not just the sandbox one):
    Meta rejects a forced tool call but takes json_schema (provider_native);
    DeepSeek thinking rejects both, so it uses json_object; everyone else uses
    the default forced tool call."""
    schema = {
        "title": "answer",
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }

    def format_mode_for(provider: str) -> str:
        # `provider` is resolved once in Agent.build (via ModelService) and
        # carried on the instance — _build_agent reads it from there.
        agent = _build_agent(provider=provider)
        agent._build_agent(checkpointer=None, output_schema=schema)
        middleware = mock_create_agent.call_args.kwargs["middleware"]
        deferred = next(
            m for m in middleware if isinstance(m, DeferredStructuredOutputMiddleware)
        )
        return deferred.format_mode

    assert format_mode_for("meta") == FORMAT_PROVIDER_NATIVE
    assert format_mode_for("deepseek") == FORMAT_JSON_OBJECT
    assert format_mode_for("openai") == FORMAT_TOOL


@patch("app.agents.runtime.create_agent")
def test_build_agent_without_output_schema(mock_create_agent):
    """Without an output schema, response_format stays None."""
    agent = _build_agent()

    agent._build_agent(checkpointer=None)

    assert mock_create_agent.call_args.kwargs["response_format"] is None
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert not any(
        isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware
    )


@patch("app.agents.runtime.create_agent")
def test_build_agent_compiles_with_deep_agent_state(mock_create_agent):
    """Every graph — sandbox or not — carries deepagents' `DeltaChannel`
    messages state, so checkpoints grow linearly with the thread."""
    agent = _build_agent()

    agent._build_agent(checkpointer=None)

    assert mock_create_agent.call_args.kwargs["state_schema"] is DeepAgentState


@patch("app.agents.runtime.create_agent")
def test_build_agent_appends_tool_error_middleware(mock_create_agent):
    """The non-sandbox path must also contain tool errors: without a
    wrap_tool_call middleware the ToolNode has no wrapper and langgraph's
    default handler re-raises anything that isn't a ToolInvocationError — an
    MCP transport failure (in a tool, or in a subagent reached through `task`)
    then crashes the whole run instead of feeding back to the model."""
    agent = _build_agent()

    agent._build_agent(checkpointer=None)

    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert isinstance(middleware[-1], ToolErrorMiddleware)


@patch("app.agents.runtime.create_agent")
def test_build_agent_sandbox_uses_the_same_create_agent_path(mock_create_agent):
    """A sandbox no longer forks the construction path: it adds deepagents'
    harness middleware to the same `create_agent` call. The caller's
    PatchToolCallsMiddleware is dropped in favour of the harness's one (langchain
    asserts against duplicates), and prompt caching closes the stack.

    `tests/agents/test_harness_parity.py` pins the assembly to what
    `create_deep_agent` built, middleware for middleware; this only checks that
    the sandbox reaches it."""
    agent = _build_agent(
        sandbox=True,
        # The harness sizes its summarization thresholds off the model, so this
        # path needs a real BaseChatModel rather than a mock.
        model=ScriptedChatModel(script=[]),
        middleware=[PatchToolCallsMiddleware(), DeferredStructuredOutputMiddleware()],
    )

    agent._build_agent(checkpointer=None)

    middleware = mock_create_agent.call_args.kwargs["middleware"]
    names = [type(m).__name__ for m in middleware]
    assert names.count("PatchToolCallsMiddleware") == 1
    assert "FilesystemMiddleware" in names
    assert names[-1] == "AnthropicPromptCachingMiddleware"
    assert "ToolErrorMiddleware" in names


@patch("app.agents.runtime.create_agent")
def test_compile_subagent_middleware_stack(mock_create_agent):
    """Subagents need their own repair/limit/retry middleware: the deepagents
    task tool invokes them as a nested graph (parent middleware doesn't
    propagate) and reports back only the last message's text — a subagent that
    exits its loop silently on invalid tool-call JSON would return an empty
    ToolMessage to the parent, and one that blows the recursion limit would
    discard its progress."""
    resolved = ResolvedAgent(config=MagicMock(), prepared=MagicMock())
    resolved.config.instructions = "You are a helper"
    resolved.config.name = "Helper"
    resolved.config.description = "helps"
    resolved.live = MagicMock()
    resolved.live.all = []
    resolved.sandbox = None
    resolved.skills = {"entries": []}

    resolved.compile(MagicMock(), datetime(2026, 1, 1, tzinfo=UTC))

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
    prepared = MagicMock()
    prepared.interrupt_on = {}

    middleware = build_parent_middleware(datetime(2026, 1, 1, tzinfo=UTC), prepared)

    types = [type(m).__name__ for m in middleware]
    assert any(isinstance(m, ModelRetryMiddleware) for m in middleware)
    assert types.index("RepairInvalidToolCallsMiddleware") < types.index(
        "HumanInTheLoopMiddleware"
    )


def test_host_notice_is_prepended_to_the_turn_input():
    """A replaced sandbox is announced as a host-authored user-role message
    ahead of the user's own, tagged so the UI can render it as an event."""
    from langchain_core.messages import HumanMessage

    from app.agents.runtime import SANDBOX_REPLACED_NOTICE, _with_host_notice

    user = HumanMessage(content="hi")
    out = _with_host_notice({"messages": [user]}, SANDBOX_REPLACED_NOTICE, "x")

    notice, echoed = out["messages"]
    assert echoed is user
    assert notice.name == "host"
    assert notice.additional_kwargs == {"host_notice": "x"}
    assert "new, empty sandbox" in notice.content


def test_host_notice_leaves_a_resume_command_alone():
    from langgraph.types import Command

    from app.agents.runtime import _with_host_notice

    command = Command(resume={"a": True})
    assert _with_host_notice(command, "note", "x") is command


async def test_open_sandbox_materializes_the_graphs_shared_skills():
    """One skill set per graph, materialized once under the shared root: a
    supervisor without code execution delegates a skill script to a sandboxed
    subagent by absolute path, and that path exists in the run's sandbox."""
    from unittest.mock import AsyncMock

    from app.sandbox.provider import SandboxSession
    from app.skills.runtime import SKILLS_ROOT

    bundle = {
        "name": "greeting",
        "description": "Use to greet",
        "instructions": "Run scripts/upload.py",
        "files": [
            {"path": "scripts/upload.py", "content": "print(1)", "encoding": "utf-8"}
        ],
    }
    shared = {"entries": [{"skill_id": "s", "bundle": bundle}]}  # as `build` merges it
    parent = MagicMock()
    parent.sandbox = None
    parent.skills = shared
    worker = MagicMock()  # the sandboxed subagent
    worker.skills = shared
    agent = Agent(
        thread=MagicMock(sandbox_id=None),
        agent=parent,
        model=MagicMock(),
        middleware=[],
        callbacks=[],
        subagents=[worker],
    )
    backend = StubSandbox("sbx-1")
    agent._remember_sandbox = AsyncMock()

    with patch(
        "app.agents.runtime.open_sandbox",
        return_value=SandboxSession(backend=backend, sandbox_id="sbx-1"),
    ):
        await agent._open_sandbox()

    assert f"{SKILLS_ROOT}/greeting/scripts/upload.py" in backend.files
    assert f"{SKILLS_ROOT}/greeting/SKILL.md" in backend.files
    agent._remember_sandbox.assert_awaited_once_with("sbx-1")
    assert agent._sandbox is not None and agent._sandbox_for(worker) is backend
    assert agent._sandbox_for(parent) is None
