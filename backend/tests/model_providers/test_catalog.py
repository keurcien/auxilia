from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.model_providers.catalog import (
    GOOGLE_ADC_SENTINEL,
    ChatModelFactory,
    provider_api_keys,
)


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-4o-mini",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5.4",
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-6-luna",
        "gpt-6-sol",
        "gpt-6-astra",
        "future-openai-model",
    ],
)
def test_openai_factory_uses_responses_for_tool_conversations(model_id: str):
    model = ChatModelFactory().create("openai", model_id, "unit-test-key")
    bound = model.bind_tools([{"name": "lookup", "parameters": {"type": "object"}}])
    # Existing Chat Completions histories must still replay after migration.
    messages = [
        HumanMessage(content="Look it up"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "lookup", "args": {}, "id": "call_lookup", "type": "tool_call"}
            ],
        ),
        ToolMessage(content="Found it", tool_call_id="call_lookup"),
    ]
    payload = model._get_request_payload(messages, **bound.kwargs)
    assert model.use_responses_api is True
    assert "messages" not in payload
    assert payload["tools"][0]["strict"] is False
    call = next(
        item for item in payload["input"] if item.get("type") == "function_call"
    )
    result = next(
        item for item in payload["input"] if item.get("type") == "function_call_output"
    )
    assert call["call_id"] == result["call_id"] == "call_lookup"
    assert result["output"] == "Found it"


@pytest.mark.parametrize(
    "model_id",
    ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1", "gpt-5.2", "gpt-5.4", "gpt-5.5"],
)
@pytest.mark.parametrize("reasoning_effort", [None, "none", "xhigh"])
@pytest.mark.parametrize("with_tools", [False, True])
def test_migrated_openai_models_serialize_responses_reasoning(
    model_id, reasoning_effort, with_tools
):
    model = ChatModelFactory().create(
        "openai", model_id, "unit-test-key", reasoning_effort=reasoning_effort
    )
    kwargs = {}
    if with_tools:
        bound = model.bind_tools([{"name": "lookup", "parameters": {"type": "object"}}])
        kwargs = bound.kwargs
    payload = model._get_request_payload([HumanMessage(content="test")], **kwargs)

    # No tools must still use Responses, and explicit "none" must not be
    # confused with an unset effort (which leaves the provider default intact).
    assert "input" in payload
    assert "messages" not in payload
    assert "reasoning_effort" not in payload
    if reasoning_effort is None:
        assert "reasoning" not in payload
    else:
        assert payload["reasoning"] == {"effort": reasoning_effort}
    if with_tools:
        assert payload["tools"][0]["type"] == "function"
    else:
        assert "tools" not in payload


def test_deepseek_factory_maps_effort_onto_thinking_params():
    factory = ChatModelFactory()
    # Default: thinking on, no explicit effort (the API defaults to high).
    model = factory.create("deepseek", "deepseek-v4-pro", "unit-test-key")
    assert model.extra_body == {"thinking": {"type": "enabled"}}
    # A level: thinking on + the effort.
    model = factory.create(
        "deepseek", "deepseek-v4-pro", "unit-test-key", reasoning_effort="max"
    )
    assert model.extra_body == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }
    # "none" turns thinking off entirely (and sends no effort).
    model = factory.create(
        "deepseek", "deepseek-v4-pro", "unit-test-key", reasoning_effort="none"
    )
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_anthropic_factory_effort_selects_adaptive_thinking():
    factory = ChatModelFactory()
    # Adaptive model, no choice → the historical medium default.
    model = factory.create("anthropic", "claude-opus-4-8", "unit-test-key")
    assert model.thinking == {"type": "adaptive", "display": "summarized"}
    assert model.reasoning_effort == "medium"
    # Adaptive model, explicit choice → the choice.
    model = factory.create(
        "anthropic", "claude-opus-4-8", "unit-test-key", reasoning_effort="max"
    )
    assert model.reasoning_effort == "max"
    # Legacy model, no choice → the historical budget format, untouched.
    model = factory.create("anthropic", "claude-sonnet-4-6", "unit-test-key")
    assert model.thinking == {"type": "enabled", "budget_tokens": 1024}
    assert model.reasoning_effort is None
    # Legacy model, explicit choice → opts into adaptive + effort.
    model = factory.create(
        "anthropic", "claude-sonnet-4-6", "unit-test-key", reasoning_effort="low"
    )
    assert model.thinking == {"type": "adaptive", "display": "summarized"}
    assert model.reasoning_effort == "low"


def test_google_factory_sends_level_xor_dynamic_budget():
    factory = ChatModelFactory()
    # thinking_level and thinking_budget are mutually exclusive on Gemini 3+.
    model = factory.create("google", "gemini-3-pro-preview", "unit-test-key")
    assert model.thinking_budget == -1
    assert model.reasoning_effort is None
    model = factory.create(
        "google", "gemini-3-pro-preview", "unit-test-key", reasoning_effort="low"
    )
    assert model.reasoning_effort == "low"
    assert model.thinking_budget is None


def test_openrouter_factory_sends_the_slug_verbatim():
    factory = ChatModelFactory()
    # No mapping table anymore: the whitelist model_id IS the OpenRouter slug.
    model = factory.create("openrouter", "z-ai/glm-5.2", "unit-test-key")
    assert model.model_name == "z-ai/glm-5.2"
    assert model.extra_body is None
    model = factory.create(
        "openrouter", "z-ai/glm-5.2", "unit-test-key", reasoning_effort="high"
    )
    assert model.extra_body == {"reasoning_effort": "high"}


def test_provider_api_keys_serves_google_via_adc_when_no_api_key():
    with (
        patch("app.model_providers.catalog.model_provider_settings") as mock_settings,
        patch(
            "app.model_providers.catalog._google_adc",
            return_value=(object(), "some-gcp-project"),
        ),
    ):
        mock_settings.google_api_key = None
        assert provider_api_keys().get("google") == GOOGLE_ADC_SENTINEL


def test_provider_api_keys_drops_google_when_no_key_and_no_adc():
    with (
        patch("app.model_providers.catalog.model_provider_settings") as mock_settings,
        patch("app.model_providers.catalog._google_adc", return_value=None),
    ):
        mock_settings.google_api_key = None
        assert "google" not in provider_api_keys()


def test_google_factory_uses_vertexai_with_adc_credentials():
    fake_credentials = object()
    with patch(
        "app.model_providers.catalog._google_adc",
        return_value=(fake_credentials, "some-gcp-project"),
    ):
        model = ChatModelFactory().create(
            "google", "gemini-3-pro-preview", GOOGLE_ADC_SENTINEL
        )
    assert model.vertexai is True
    assert model.credentials is fake_credentials
    assert model.project == "some-gcp-project"


def test_google_factory_uses_api_key_when_provided():
    model = ChatModelFactory().create("google", "gemini-3-pro-preview", "a-real-key")
    assert model.vertexai is None
    assert model.credentials is None


@pytest.mark.parametrize(
    ("tool_name", "properties", "arguments"),
    [
        (
            "find-product",
            {
                "product_variant_id": {"type": "string"},
                "product_id": {"type": "string"},
            },
            {"product_variant_id": "known-variant"},
        ),
        (
            "find-next-brand-sale",
            {"sale_id": {"type": "string"}, "product_variant_id": {"type": "string"}},
            {"sale_id": "known-sale"},
        ),
        (
            "get-sale-info",
            {"saleId": {"type": "string"}, "query": {"type": "string"}},
            {"query": "Known brand"},
        ),
    ],
)
def test_responses_preserves_optional_mcp_arguments(tool_name, properties, arguments):
    schema = {"type": "object", "properties": properties}
    tool = StructuredTool(
        name=tool_name,
        description="Only provide known identifiers.",
        args_schema=schema,
        func=lambda **kwargs: kwargs,
    )
    model = ChatModelFactory().create(
        "openai", "gpt-5.6-luna", "unit-test-key", reasoning_effort="high"
    )
    bound = model.bind_tools([tool])
    payload = model._get_request_payload([HumanMessage(content="test")], **bound.kwargs)

    # Assert the actual wire payload, not just a flag on the model: omitting
    # strict lets Responses promote every property to a required argument.
    assert payload["tools"][0]["strict"] is False
    assert payload["tools"][0]["parameters"] == schema
    assert tool.invoke(arguments) == arguments
    assert payload["reasoning"]["effort"] == "high"
    assert model.max_retries == 0


def test_responses_preserves_explicit_strict_structured_output():
    model = ChatModelFactory().create("openai", "gpt-5.6-luna", "unit-test-key")
    tool = {
        "name": "answer",
        "parameters": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
    bound = model.bind_tools([tool], strict=True)
    payload = model._get_request_payload([HumanMessage(content="test")], **bound.kwargs)
    assert payload["tools"][0]["strict"] is True


@pytest.mark.parametrize(
    ("provider", "model_id"),
    [("openrouter", "z-ai/glm-5.2"), ("xiaomi", "mimo-v2-pro"), ("meta", "muse-spark")],
)
def test_compatible_providers_keep_chat_completions(provider, model_id):
    model = ChatModelFactory().create(provider, model_id, "unit-test-key")
    bound = model.bind_tools([{"name": "lookup", "parameters": {"type": "object"}}])
    assert "strict" not in bound.kwargs["tools"][0]["function"]
    payload = model._get_request_payload([HumanMessage(content="test")], **bound.kwargs)
    assert "messages" in payload
    assert "input" not in payload
