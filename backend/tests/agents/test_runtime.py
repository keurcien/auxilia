from unittest.mock import MagicMock, patch

from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

from app.agents.runtime import Agent
from app.agents.structured_output import DeferredStructuredOutputMiddleware
from app.agents.tool_errors import ToolErrorMiddleware
from app.model_providers.catalog import Model


def _build_agent(*, has_code_interpreter: bool = False, middleware=None) -> Agent:
    resolved = MagicMock()
    resolved.config.has_code_interpreter = has_code_interpreter
    resolved.config.instructions = "You are a test agent"
    resolved.live.all = []
    return Agent(
        thread=MagicMock(),
        agent=resolved,
        model=MagicMock(),
        middleware=middleware if middleware is not None else [],
        callbacks=[],
        subagents=[],
    )


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
def test_build_agent_routes_auto_only_provider_to_provider_native(mock_create_agent):
    """The formatting middleware is flagged provider_native for providers whose
    API only allows tool_choice='auto' (Meta), and not for others — this is what
    keeps Meta off the forced-tool-call path (and must reach the non-sandbox
    create_agent middleware, not just the sandbox one)."""
    schema = {
        "title": "answer",
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }
    models = [
        Model(name="auto-model", provider="meta"),
        Model(name="forced-model", provider="deepseek"),
    ]

    def provider_native_for(model_id: str) -> bool:
        agent = _build_agent()
        agent.thread.model_id = model_id
        with patch("app.agents.runtime.MODELS", models):
            agent._build_agent(checkpointer=None, output_schema=schema)
        middleware = mock_create_agent.call_args.kwargs["middleware"]
        deferred = next(
            m for m in middleware if isinstance(m, DeferredStructuredOutputMiddleware)
        )
        return deferred.provider_native

    assert provider_native_for("auto-model") is True
    assert provider_native_for("forced-model") is False


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


@patch("app.sandbox.tools.create_sandbox_tools", return_value=[])
@patch("app.agents.runtime.create_deep_agent")
@patch("app.agents.runtime.sandbox_settings")
def test_build_agent_sandbox_dispatches_to_deep_agent(
    mock_settings, mock_create_deep_agent, _mock_tools
):
    """With a code interpreter + sandbox enabled, the build goes through
    create_deep_agent: ToolErrorMiddleware is appended and the caller's
    PatchToolCallsMiddleware is dropped (deepagents injects its own)."""
    mock_settings.enabled = True
    agent = _build_agent(
        has_code_interpreter=True,
        middleware=[PatchToolCallsMiddleware(), DeferredStructuredOutputMiddleware()],
    )

    agent._build_agent(checkpointer=None)

    middleware = mock_create_deep_agent.call_args.kwargs["middleware"]
    # Our PatchToolCallsMiddleware is filtered out (deepagents adds its own).
    assert not any(isinstance(m, PatchToolCallsMiddleware) for m in middleware)
    # ToolErrorMiddleware is appended last so tool failures feed back as messages.
    assert isinstance(middleware[-1], ToolErrorMiddleware)
