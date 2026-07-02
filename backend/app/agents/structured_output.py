"""Defer structured output to a final formatting turn so the agent keeps its tools.

Binding ``response_format`` on every model call (what ``create_agent`` does by
default) breaks the ReAct loop in practice: with the provider's constrained
decoding active, the model goes straight to emitting schema-conforming JSON
instead of calling tools — and, having gathered nothing, fills the schema with
fabricated values.

``DeferredStructuredOutputMiddleware`` keeps the schema out of the loop:

1. Every model call runs with ``response_format`` stripped, so the model calls
   tools and reasons exactly as it would without a schema.
2. When a call produces no tool calls (the final answer), one extra model call
   is made — same conversation plus a formatting instruction — with the
   original ``response_format`` restored. langchain's strategy resolution
   (provider-native vs. forced tool call) applies only to that turn, and the
   parsed result flows through the normal ``structured_response`` channel, so
   it is checkpointed and returned in the run state like any other update.

The synthetic formatting instruction is only part of the model request, never
of the returned messages, so it does not pollute the thread history. The
agent must still be built with ``response_format`` set — that is what registers
the structured-output machinery this middleware re-enables on the last turn.

The formatting turn's result is validated against the JSON schema before it is
accepted: langchain returns raw-JSON-schema payloads verbatim (no validation),
so a model that answers the formatting turn with an empty or partial tool call
would otherwise surface ``{}`` as a successful structured response. An invalid
result gets one retry with the rejection fed back (the failed attempt's
messages are discarded); a second failure raises ``StructuredOutputError`` so
the run fails loudly instead of returning garbage.

Every message the formatting turn produces is tagged with
``STRUCTURED_OUTPUT_FLAG`` in ``response_metadata`` (checkpointed, but never
sent back to the provider), so read paths can recognize formatting artifacts —
the raw-JSON message on the provider-native path, the synthetic tool-call pair
on the ToolStrategy path — and keep them out of the rendered chat history.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import jsonschema
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.exceptions import StructuredOutputError


FORMAT_INSTRUCTION = (
    "Based on your answer above, provide the final response in the requested "
    "structured format. Use only information from this conversation; do not "
    "invent values."
)

FORMAT_RETRY_INSTRUCTION = (
    "Based on your answer above, provide the final response in the requested "
    "structured format. Your previous attempt was rejected: {error}. Fill in "
    "every required field, using only information from this conversation; do "
    "not invent values."
)

STRUCTURED_OUTPUT_FLAG = "structured_output"


def is_structured_output_artifact(message: Any) -> bool:
    """True for messages produced by the formatting turn (chat-history noise)."""
    metadata = getattr(message, "response_metadata", None) or {}
    return bool(metadata.get(STRUCTURED_OUTPUT_FLAG))


def validate_structured_response(value: Any, response_format: Any) -> str | None:
    """Return why ``value`` is not a valid structured response, or None if it is.

    ``response_format`` is either the raw JSON Schema dict or a langchain
    strategy (``ToolStrategy`` / ``ProviderStrategy``) wrapping one. langchain
    validates pydantic/dataclass schemas itself but passes raw-JSON-schema
    payloads through verbatim (``_parse_with_schema``), so an empty tool call
    (``{}``) would otherwise count as a successful structured response — this
    is the check that rejects it. Non-dict schemas are left to langchain.
    """
    if value is None:
        return "no structured response was produced"
    schema = (
        response_format
        if isinstance(response_format, dict)
        else getattr(response_format, "schema", None)
    )
    if not isinstance(schema, dict):
        return None
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        return exc.message
    return None


def _tag(message: BaseMessage) -> BaseMessage:
    return message.model_copy(
        update={
            "response_metadata": {
                **message.response_metadata,
                STRUCTURED_OUTPUT_FLAG: True,
            }
        }
    )


class DeferredStructuredOutputMiddleware(AgentMiddleware):
    """Apply ``response_format`` only on a final formatting turn."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if request.response_format is None:
            return await handler(request)

        # Loop turn: run unconstrained so the model can freely call tools.
        # invalid_tool_calls also keep the loop going: the message must stay
        # last in state so RepairInvalidToolCallsMiddleware (after_model, keyed
        # on messages[-1]) can answer it with an error ToolMessage and the
        # model can retry — formatting waits for a clean final answer.
        response = await handler(request.override(response_format=None))
        loop_continues = any(
            isinstance(m, AIMessage) and (m.tool_calls or m.invalid_tool_calls)
            for m in response.result
        )
        if loop_continues:
            return response

        # Final answer reached: one constrained call formats it. The original
        # response_format object is passed through untouched so the strategy
        # (and ToolStrategy tool names) resolved at agent setup still apply.
        conversation = [*request.messages, *response.result]
        format_response = await handler(
            request.override(messages=[*conversation, HumanMessage(FORMAT_INSTRUCTION)])
        )
        error = validate_structured_response(
            format_response.structured_response, request.response_format
        )
        if error is not None:
            # One retry with the rejection fed back. The failed attempt's
            # messages are dropped entirely — they may carry a dangling
            # structured-output tool call that must not reach state.
            format_response = await handler(
                request.override(
                    messages=[
                        *conversation,
                        HumanMessage(FORMAT_RETRY_INSTRUCTION.format(error=error)),
                    ]
                )
            )
            error = validate_structured_response(
                format_response.structured_response, request.response_format
            )
            if error is not None:
                raise StructuredOutputError(
                    f"Model failed to produce a valid structured response: {error}"
                )
        return ModelResponse(
            result=[*response.result, *(_tag(m) for m in format_response.result)],
            structured_response=format_response.structured_response,
        )
