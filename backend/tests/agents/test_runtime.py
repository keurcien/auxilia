from unittest.mock import MagicMock, patch

from app.agents.runtime import Agent
from app.agents.structured_output import DeferredStructuredOutputMiddleware


def _make_agent() -> Agent:
    resolved = MagicMock()
    resolved.config.has_code_interpreter = False
    resolved.config.instructions = "You are a test agent"
    resolved.live.all = []
    return Agent(
        thread=MagicMock(),
        agent=resolved,
        model=MagicMock(),
        middleware=[],
        callbacks=[],
        subagents=[],
    )


@patch("app.agents.runtime.create_agent")
def test_build_agent_forwards_output_schema(mock_create_agent):
    """An output schema is passed to create_agent as response_format."""
    agent = _make_agent()
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
    assert any(
        isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware
    )


@patch("app.agents.runtime.create_agent")
def test_build_agent_without_output_schema(mock_create_agent):
    """Without an output schema, response_format stays None."""
    agent = _make_agent()

    agent._build_agent(checkpointer=None)

    assert mock_create_agent.call_args.kwargs["response_format"] is None
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    assert not any(
        isinstance(m, DeferredStructuredOutputMiddleware) for m in middleware
    )
