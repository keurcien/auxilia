from unittest.mock import MagicMock

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.structured_output import (
    FORMAT_INSTRUCTION,
    DeferredStructuredOutputMiddleware,
)


SCHEMA = {
    "title": "answer",
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
}


def _make_request(response_format=SCHEMA) -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=[HumanMessage("What is 2 + 2?")],
        response_format=response_format,
    )


def _handler_recording(responses: list[ModelResponse], calls: list[ModelRequest]):
    async def handler(request: ModelRequest) -> ModelResponse:
        calls.append(request)
        return responses[len(calls) - 1]

    return handler


async def test_no_response_format_passes_through():
    """Without a response_format, the middleware is a no-op."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request(response_format=None)
    expected = ModelResponse(result=[AIMessage("4")])
    calls: list[ModelRequest] = []

    response = await middleware.awrap_model_call(
        request, _handler_recording([expected], calls)
    )

    assert response is expected
    assert len(calls) == 1
    assert calls[0] is request


async def test_loop_turn_runs_unconstrained():
    """A turn that produces tool calls runs without response_format and is returned as-is."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request()
    tool_call_response = ModelResponse(
        result=[
            AIMessage(
                "",
                tool_calls=[{"name": "search", "args": {}, "id": "call_1"}],
            )
        ]
    )
    calls: list[ModelRequest] = []

    response = await middleware.awrap_model_call(
        request, _handler_recording([tool_call_response], calls)
    )

    assert response is tool_call_response
    assert len(calls) == 1
    assert calls[0].response_format is None


async def test_final_turn_adds_constrained_formatting_call():
    """The final answer triggers one extra call with response_format restored."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request()
    final_answer = AIMessage("2 + 2 = 4")
    formatted = AIMessage('{"answer": 4}')
    calls: list[ModelRequest] = []

    response = await middleware.awrap_model_call(
        request,
        _handler_recording(
            [
                ModelResponse(result=[final_answer]),
                ModelResponse(result=[formatted], structured_response={"answer": 4}),
            ],
            calls,
        ),
    )

    assert len(calls) == 2
    # Loop turn: schema stripped.
    assert calls[0].response_format is None
    # Formatting turn: original schema restored, conversation extended with the
    # final answer and the formatting instruction (instruction stays out of state).
    assert calls[1].response_format == SCHEMA
    assert calls[1].messages[-2:] == [final_answer, HumanMessage(FORMAT_INSTRUCTION)]
    # Combined response: both AI messages land in state, parsed object included.
    assert response.result == [final_answer, formatted]
    assert response.structured_response == {"answer": 4}
