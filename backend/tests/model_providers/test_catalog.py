from unittest.mock import patch

import pytest

from app.model_providers.catalog import (
    GOOGLE_ADC_SENTINEL,
    ChatModelFactory,
    provider_api_keys,
)


@pytest.mark.parametrize(
    ("model_id", "expects_responses_api"),
    [
        # gpt-5.6 reasoning models reject function tools on chat completions —
        # they must go through the Responses API.
        ("gpt-5.6-luna", True),
        ("gpt-5.6-sol", True),
        ("gpt-5.6-terra", True),
        # The rest of the family works on the default chat-completions path.
        ("gpt-5.5", False),
        ("gpt-5", False),
        ("gpt-4o-mini", False),
    ],
)
def test_openai_factory_routes_gpt56_through_responses_api(
    model_id: str, expects_responses_api: bool
):
    model = ChatModelFactory().create("openai", model_id, "unit-test-key")
    assert model.use_responses_api is expects_responses_api


def test_openai_factory_passes_reasoning_effort_through():
    model = ChatModelFactory().create(
        "openai", "gpt-5.2", "unit-test-key", reasoning_effort="xhigh"
    )
    assert model.reasoning_effort == "xhigh"
    # No explicit choice → nothing sent, the provider default applies.
    model = ChatModelFactory().create("openai", "gpt-5.2", "unit-test-key")
    assert model.reasoning_effort is None


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
