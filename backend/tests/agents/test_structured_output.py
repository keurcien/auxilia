from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.agents.structured_output import (
    FORMAT_INSTRUCTION,
    DeferredStructuredOutputMiddleware,
    is_structured_output_artifact,
    validate_structured_response,
)
from app.exceptions import StructuredOutputError


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


async def test_invalid_tool_calls_keep_the_loop_going():
    """Malformed tool calls are not a final answer: the response passes through
    untouched so RepairInvalidToolCallsMiddleware (keyed on messages[-1]) can
    feed the error back for a retry instead of formatting a failed attempt."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request()
    invalid_response = ModelResponse(
        result=[
            AIMessage(
                "",
                invalid_tool_calls=[
                    {
                        "name": "search",
                        "args": '{"q": truncated',
                        "id": "call_1",
                        "error": "Invalid JSON",
                    }
                ],
            )
        ]
    )
    calls: list[ModelRequest] = []

    response = await middleware.awrap_model_call(
        request, _handler_recording([invalid_response], calls)
    )

    assert response is invalid_response
    assert len(calls) == 1


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
    assert response.structured_response == {"answer": 4}
    prose, structured = response.result
    assert prose == final_answer
    assert structured.content == formatted.content
    # The formatting artifact is tagged so read paths can hide it from the
    # rendered chat history; the prose answer is not.
    assert is_structured_output_artifact(structured)
    assert not is_structured_output_artifact(prose)


async def test_invalid_formatting_result_retries_with_error_feedback():
    """An empty structured response (e.g. an empty tool call) triggers one
    retry whose instruction carries the rejection; the failed attempt's
    messages never reach state."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request()
    final_answer = AIMessage("2 + 2 = 4")
    failed_attempt = AIMessage(
        "", tool_calls=[{"name": "response_format", "args": {}, "id": "call_1"}]
    )
    formatted = AIMessage('{"answer": 4}')
    calls: list[ModelRequest] = []

    response = await middleware.awrap_model_call(
        request,
        _handler_recording(
            [
                ModelResponse(result=[final_answer]),
                ModelResponse(result=[failed_attempt], structured_response={}),
                ModelResponse(result=[formatted], structured_response={"answer": 4}),
            ],
            calls,
        ),
    )

    assert len(calls) == 3
    # The retry replaces the plain instruction with one carrying the rejection,
    # on the same conversation (no trace of the failed attempt).
    retry_instruction = calls[2].messages[-1]
    assert "rejected" in retry_instruction.content
    assert "'answer' is a required property" in retry_instruction.content
    assert failed_attempt not in calls[2].messages
    # Only the prose answer and the successful attempt land in state.
    assert response.structured_response == {"answer": 4}
    assert failed_attempt not in response.result
    assert [m.content for m in response.result] == [
        final_answer.content,
        formatted.content,
    ]


async def test_invalid_formatting_result_twice_raises():
    """A second invalid structured response fails the run instead of
    silently returning garbage to the caller."""
    middleware = DeferredStructuredOutputMiddleware()
    request = _make_request()
    empty = ModelResponse(
        result=[AIMessage("")],
        structured_response={},
    )
    calls: list[ModelRequest] = []

    with pytest.raises(StructuredOutputError, match="required property"):
        await middleware.awrap_model_call(
            request,
            _handler_recording(
                [ModelResponse(result=[AIMessage("4")]), empty, empty], calls
            ),
        )
    assert len(calls) == 3


class _Answer(BaseModel):
    answer: int


@pytest.mark.parametrize(
    ("value", "response_format", "is_valid"),
    [
        (None, SCHEMA, False),  # formatting turn produced nothing
        ({}, SCHEMA, False),  # empty tool-call args (the deepseek incident)
        ({"answer": "four"}, SCHEMA, False),  # wrong type
        ({"answer": 4}, SCHEMA, True),
        ({}, ToolStrategy(schema=SCHEMA), False),  # schema wrapped in a strategy
        ({"answer": 4}, ToolStrategy(schema=SCHEMA), True),
        ({}, ToolStrategy(schema=_Answer), True),  # pydantic: langchain validates
    ],
)
def test_validate_structured_response(value, response_format, is_valid):
    error = validate_structured_response(value, response_format)
    assert (error is None) is is_valid
