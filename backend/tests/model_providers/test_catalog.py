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
