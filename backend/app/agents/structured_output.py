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
result is retried up to ``MAX_FORMAT_ATTEMPTS`` times with the rejection fed
back each time (the failed attempt's messages are discarded); exhausting them
raises ``StructuredOutputError`` so the run fails loudly instead of returning
garbage.

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
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.exceptions import StructuredOutputError


logger = logging.getLogger(__name__)

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

# json_object mode carries the schema in the prompt (the provider enforces only
# "valid JSON", not the shape — validate_structured_response does the rest).
JSON_OBJECT_INSTRUCTION = (
    "Based on your answer above, respond with a single JSON object matching this "
    "JSON Schema. Output only the JSON object — no prose, no code fences. Use "
    "only information from this conversation; do not invent values.\n\n"
    "JSON Schema:\n{schema}"
)

JSON_OBJECT_RETRY_INSTRUCTION = (
    "Based on your answer above, respond with a single JSON object matching the "
    "JSON Schema below. Your previous attempt was rejected: {error}. Fill in "
    "every required field, output only the JSON object (no prose, no code "
    "fences), and use only information from this conversation.\n\n"
    "JSON Schema:\n{schema}"
)

# Formatting turns before giving up. Each attempt feeds the prior rejection back,
# so extra tries cut the tail of transient omissions (e.g. a dropped required key).
MAX_FORMAT_ATTEMPTS = 3

STRUCTURED_OUTPUT_FLAG = "structured_output"

# Formatting strategy for the final structured-output turn.
#   FORMAT_TOOL           — langchain default: a forced (named) tool call.
#   FORMAT_PROVIDER_NATIVE — provider-native json_schema (ProviderStrategy).
#   FORMAT_JSON_OBJECT     — legacy json_object response_format; the schema rides
#                            in the prompt and we validate the parsed JSON.
FORMAT_TOOL = "tool"
FORMAT_PROVIDER_NATIVE = "provider_native"
FORMAT_JSON_OBJECT = "json_object"

# Formatting strategy per model provider (see the modes above). Providers not
# listed use the default forced tool call — the only path that constrains the
# provider itself. The others exist because some provider APIs reject it:
#   - Meta's Model API rejects a forced tool_choice with a 400 but accepts the
#     provider-native json_schema, so it uses FORMAT_PROVIDER_NATIVE.
#   - DeepSeek's thinking mode rejects BOTH a forced tool_choice ("Thinking mode
#     does not support this tool_choice") AND json_schema ("This response_format
#     type is unavailable now"); only the legacy json_object mode works, so it
#     uses FORMAT_JSON_OBJECT.
PROVIDER_FORMAT_MODES: dict[str, str] = {
    "meta": FORMAT_PROVIDER_NATIVE,
    "deepseek": FORMAT_JSON_OBJECT,
}


def is_structured_output_artifact(message: Any) -> bool:
    """True for messages produced by the formatting turn (chat-history noise)."""
    metadata = getattr(message, "response_metadata", None) or {}
    return bool(metadata.get(STRUCTURED_OUTPUT_FLAG))


def _schema_of(response_format: Any) -> Any:
    """The JSON Schema inside a raw-schema dict or a langchain strategy wrapper
    (``ToolStrategy`` / ``ProviderStrategy`` both expose ``.schema``)."""
    if isinstance(response_format, dict):
        return response_format
    return getattr(response_format, "schema", None)


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
    schema = _schema_of(response_format)
    if not isinstance(schema, dict):
        return None
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        return exc.message
    return None


def _message_text(message: BaseMessage) -> str:
    """The text content of a message, flattening the list-of-parts form some
    providers use so json_object output can be parsed as a single string."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content or ""


def _parse_json_object(messages: list[BaseMessage]) -> tuple[Any, str | None]:
    """Parse the last AIMessage as a JSON object: ``(value, None)`` on success,
    ``(None, error)`` otherwise. json_object mode returns bare JSON, but a stray
    ```` ```json ```` fence is stripped defensively before parsing."""
    ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if ai is None:
        return None, "no structured response was produced"
    text = _message_text(ai).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        return json.loads(text), None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"response was not valid JSON: {exc}"


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
    """Apply ``response_format`` only on a final formatting turn.

    ``format_mode`` selects how that final turn constrains the output, for
    providers whose API rejects the langchain default (a forced tool call):

    - ``FORMAT_TOOL`` (default): forced tool call — the provider enforces the
      schema.
    - ``FORMAT_PROVIDER_NATIVE``: provider-native json_schema (``ProviderStrategy``)
      — for providers that only allow ``tool_choice="auto"`` (Meta).
    - ``FORMAT_JSON_OBJECT``: legacy json_object mode — for providers that reject
      both a forced tool call and json_schema (DeepSeek's thinking mode). The
      schema rides in the prompt and the parsed JSON is validated here.
    """

    def __init__(self, format_mode: str = FORMAT_TOOL) -> None:
        super().__init__()
        self.format_mode = format_mode

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

        # Final answer reached: a constrained call formats it. Each failed
        # attempt's messages are dropped entirely — they may carry a dangling
        # structured-output tool call that must not reach state — and the
        # rejection is fed back to the next attempt.
        if self.format_mode == FORMAT_JSON_OBJECT:
            return await self._format_via_json_object(request, handler, response)
        return await self._format_via_strategy(request, handler, response)

    async def _format_via_strategy(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        response: ModelResponse,
    ) -> ModelResponse:
        """Format via langchain's structured-output machinery: the default forced
        tool call, or (Meta) the provider-native json_schema strategy. The parsed
        result flows back on ``structured_response``."""
        conversation = [*request.messages, *response.result]
        instruction = FORMAT_INSTRUCTION
        response_format = request.response_format
        if self.format_mode == FORMAT_PROVIDER_NATIVE:
            response_format = ProviderStrategy(schema=_schema_of(response_format))
        error: str | None = None
        for _ in range(MAX_FORMAT_ATTEMPTS):
            format_response = await handler(
                request.override(
                    messages=[*conversation, HumanMessage(instruction)],
                    response_format=response_format,
                )
            )
            error = validate_structured_response(
                format_response.structured_response, response_format
            )
            if error is None:
                return self._combine(
                    response,
                    format_response.result,
                    format_response.structured_response,
                )
            logger.warning(
                "structured-output rejected: %s | shape=%s",
                error,
                _payload_shape(format_response.structured_response),
            )
            instruction = FORMAT_RETRY_INSTRUCTION.format(error=error)
        raise StructuredOutputError(
            f"Model failed to produce a valid structured response: {error}"
        )

    async def _format_via_json_object(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        response: ModelResponse,
    ) -> ModelResponse:
        """Format via legacy json_object mode (DeepSeek thinking): bind
        ``response_format={"type": "json_object"}`` so the provider emits bare
        JSON, carry the schema in the prompt (json_object enforces only "is
        JSON", not the shape), then parse and validate here. No forced tool call
        or json_schema is ever sent, both of which that API rejects."""
        conversation = [*request.messages, *response.result]
        schema = _schema_of(request.response_format)
        schema_text = json.dumps(schema)
        instruction = JSON_OBJECT_INSTRUCTION.format(schema=schema_text)
        model_settings = {
            **request.model_settings,
            "response_format": {"type": "json_object"},
        }
        error: str | None = None
        for _ in range(MAX_FORMAT_ATTEMPTS):
            # response_format=None so no strategy is applied (no tool_choice, no
            # json_schema); tools dropped so the turn only emits the JSON answer.
            format_response = await handler(
                request.override(
                    messages=[*conversation, HumanMessage(instruction)],
                    response_format=None,
                    tools=[],
                    model_settings=model_settings,
                )
            )
            value, error = _parse_json_object(format_response.result)
            if error is None:
                error = validate_structured_response(value, request.response_format)
            if error is None:
                return self._combine(response, format_response.result, value)
            logger.warning(
                "structured-output rejected: %s | shape=%s",
                error,
                _payload_shape(value),
            )
            instruction = JSON_OBJECT_RETRY_INSTRUCTION.format(
                error=error, schema=schema_text
            )
        raise StructuredOutputError(
            f"Model failed to produce a valid structured response: {error}"
        )

    @staticmethod
    def _combine(
        response: ModelResponse,
        format_messages: list[BaseMessage],
        structured_response: Any,
    ) -> ModelResponse:
        """Prose answer + tagged formatting messages in state, parsed object on
        ``structured_response``. Formatting messages are tagged so read paths can
        keep them out of the rendered chat history."""
        return ModelResponse(
            result=[*response.result, *(_tag(m) for m in format_messages)],
            structured_response=structured_response,
        )
