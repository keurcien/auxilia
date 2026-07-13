"""Defer structured output to a final formatting turn so the agent keeps its tools.

Binding ``response_format`` on every model call (what ``create_agent`` does by
default) breaks the ReAct loop in practice: with the provider's constrained
decoding active, the model goes straight to emitting schema-conforming JSON
instead of calling tools — and, having gathered nothing, fills the schema with
fabricated values.

``DeferredStructuredOutputMiddleware`` keeps the schema out of the loop:

1. Every model call runs with ``response_format`` stripped, so the model calls
   tools and reasons exactly as it would without a schema.
2. When a call produces no tool calls (the final answer), formatting calls are
   made with the business tools removed and the original ``response_format``
   restored. langchain's strategy resolution (provider-native vs. forced tool
   call) applies only to those turns. A final JSON-only fallback escapes a
   provider that deterministically repeats an invalid structured tool call.

The synthetic formatting instruction is only part of the model request, never
of the returned messages, so it does not pollute the thread history. The
agent must still be built with ``response_format`` set — that is what registers
the structured-output machinery this middleware re-enables on the last turn.

The formatting turn's result is validated against the JSON schema before it is
accepted: langchain returns raw-JSON-schema payloads verbatim (no validation),
so a model that answers the formatting turn with an empty or partial tool call
would otherwise surface ``{}`` as a successful structured response. An invalid
result is retried up to ``MAX_FORMAT_ATTEMPTS`` times with the schema and
rejected candidate fed back each time (the failed attempt's messages are
discarded); exhausting them raises ``StructuredOutputError`` so the run fails
loudly instead of returning garbage.

Every message the formatting turn produces is tagged with
``STRUCTURED_OUTPUT_FLAG`` in ``response_metadata`` (checkpointed, but never
sent back to the provider), so read paths can recognize formatting artifacts —
the raw-JSON message on the provider-native path, the synthetic tool-call pair
on the ToolStrategy path — and keep them out of the rendered chat history.
"""

from __future__ import annotations

import json
import logging
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


logger = logging.getLogger(__name__)

FORMAT_INSTRUCTION = (
    "Based on your answer above, provide the final response in the requested "
    "structured format. Return every required field. Use only information from "
    "this conversation; do not invent values."
)

FORMAT_RETRY_INSTRUCTION = (
    "Correct the rejected structured response below. It failed validation: "
    "{error}. Preserve its valid information and fill in every required field, "
    "using only information from this conversation; do not invent values."
)

# Formatting turns before giving up. The final attempt deliberately switches from
# the provider/tool structured-output strategy to a JSON-only response that we
# parse and validate locally. This escapes providers that deterministically emit
# the same incomplete tool call on every constrained retry.
MAX_FORMAT_ATTEMPTS = 3

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
    schema = _response_schema(response_format)
    if not isinstance(schema, dict):
        return None
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        return exc.message
    return None


def _response_schema(response_format: Any) -> dict[str, Any] | None:
    schema = (
        response_format
        if isinstance(response_format, dict)
        else getattr(response_format, "schema", None)
    )
    return schema if isinstance(schema, dict) else None


def _prompt_json(value: Any) -> str:
    """Serialize schema/candidate data for a request-only repair prompt.

    Values may contain customer data, so this output must never be logged. It is
    sent only back to the same model that produced/consumed the data already.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _format_instruction(response_format: Any) -> str:
    schema = _response_schema(response_format)
    if schema is None:
        return FORMAT_INSTRUCTION
    required = schema.get("required", [])
    return (
        f"{FORMAT_INSTRUCTION}\n\n"
        f"Required fields: {_prompt_json(required)}\n"
        f"JSON Schema:\n{_prompt_json(schema)}"
    )


def _retry_instruction(error: str, response_format: Any, candidate: Any) -> str:
    schema = _response_schema(response_format)
    schema_text = _prompt_json(schema) if schema is not None else "unavailable"
    return (
        f"{FORMAT_RETRY_INSTRUCTION.format(error=error)}\n\n"
        f"Rejected response:\n{_prompt_json(candidate)}\n\n"
        f"JSON Schema:\n{schema_text}\n\n"
        "Return only the corrected JSON value."
    )


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(block.get("text", block.get("content", "")))
        for block in content
        if isinstance(block, dict)
        and isinstance(block.get("text", block.get("content", "")), str)
    )


def _parse_json_response(response: ModelResponse) -> tuple[Any, str | None]:
    """Parse a JSON-only fallback response, tolerating a fenced JSON block."""
    message = next(
        (m for m in reversed(response.result) if isinstance(m, AIMessage)), None
    )
    text = _message_text(message).strip() if message is not None else ""
    candidates = [text]
    if text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            candidates.insert(0, text[first_newline + 1 : -3].strip())
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError as exc:
            last_error = exc
    detail = last_error.msg if last_error is not None else "empty model response"
    return None, f"JSON-only fallback did not return valid JSON: {detail}"


def _payload_shape(value: Any) -> str:
    """A non-sensitive descriptor of a rejected payload for logs: its keys (a
    dropped required field is the usual culprit) or type — never the values,
    which carry customer text / reasoning that must not leak into logs."""
    if isinstance(value, dict):
        return f"dict{sorted(value)}"
    return type(value).__name__


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

        # Final answer reached: a constrained call formats it. The original
        # response_format object is passed through untouched so the strategy
        # (and ToolStrategy tool names) resolved at agent setup still apply.
        # Each failed attempt's messages are dropped entirely — they may carry a
        # dangling structured-output tool call that must not reach state — and the
        # rejection is fed back to the next attempt.
        conversation = [*request.messages, *response.result]
        instruction = _format_instruction(request.response_format)
        error: str | None = None
        for attempt in range(MAX_FORMAT_ATTEMPTS):
            # Local fallback validation is defined only for raw JSON Schema.
            # Pydantic/dataclass strategies remain constrained so LangChain can
            # construct and validate their typed result.
            is_json_fallback = (
                attempt == MAX_FORMAT_ATTEMPTS - 1
                and _response_schema(request.response_format) is not None
            )
            format_response = await handler(
                request.override(
                    messages=[*conversation, HumanMessage(instruction)],
                    # Formatting must not call business tools. LangChain re-adds
                    # its synthetic response tool for ToolStrategy, making it the
                    # only possible tool on constrained attempts.
                    tools=[],
                    response_format=(
                        None if is_json_fallback else request.response_format
                    ),
                )
            )
            if is_json_fallback:
                candidate, parse_error = _parse_json_response(format_response)
                error = parse_error or validate_structured_response(
                    candidate, request.response_format
                )
            else:
                candidate = format_response.structured_response
                error = validate_structured_response(candidate, request.response_format)
            if error is None:
                return ModelResponse(
                    result=[
                        *response.result,
                        *(_tag(m) for m in format_response.result),
                    ],
                    structured_response=candidate,
                )
            logger.warning(
                "structured-output rejected: %s | shape=%s",
                error,
                _payload_shape(candidate),
            )
            instruction = _retry_instruction(error, request.response_format, candidate)
        raise StructuredOutputError(
            f"Model failed to produce a valid structured response: {error}"
        )
