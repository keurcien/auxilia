from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.model_providers import federation
from app.model_providers.catalog import (
    WORKLOAD_IDENTITY_SENTINEL,
    ChatModelFactory,
    FederatedChatAnthropic,
    ResponsesChatOpenAI,
    provider_api_keys,
)
from app.model_providers.settings import ModelProviderSettings


ANTHROPIC_IDS = {
    "anthropic_federation_rule_id": "fdrl_test",
    "anthropic_organization_id": "00000000-0000-4000-8000-000000000000",
    "anthropic_service_account_id": "svac_test",
    "anthropic_workspace_id": "wrkspc_test",
}
OPENAI_IDS = {
    "openai_identity_provider_id": "idp_test",
    "openai_service_account_id": "svcacct_test",
}


def _settings(**values) -> ModelProviderSettings:
    return ModelProviderSettings(_env_file=None, **values)


@pytest.fixture
def federated_settings():
    # API keys still configured, as during a migration: federation must win.
    settings = _settings(
        **ANTHROPIC_IDS,
        **OPENAI_IDS,
        anthropic_api_key="legacy-anthropic-key",
        openai_api_key="legacy-openai-key",
    )
    with (
        patch("app.model_providers.catalog.model_provider_settings", settings),
        patch("app.model_providers.federation.model_provider_settings", settings),
        patch("app.model_providers.catalog._google_adc", return_value=None),
    ):
        federation.anthropic_credentials.cache_clear()
        federation.openai_clients.cache_clear()
        yield settings
    federation.anthropic_credentials.cache_clear()
    federation.openai_clients.cache_clear()


def test_provider_api_keys_prefers_workload_identity(federated_settings):
    keys = provider_api_keys()
    assert keys["anthropic"] == WORKLOAD_IDENTITY_SENTINEL
    assert keys["openai"] == WORKLOAD_IDENTITY_SENTINEL


def test_provider_api_keys_keeps_api_keys_without_federation():
    settings = _settings(anthropic_api_key="a-key", openai_api_key="o-key")
    with (
        patch("app.model_providers.catalog.model_provider_settings", settings),
        patch("app.model_providers.catalog._google_adc", return_value=None),
    ):
        keys = provider_api_keys()
    assert keys["anthropic"] == "a-key"
    assert keys["openai"] == "o-key"


@pytest.mark.parametrize(
    "partial",
    [
        {"anthropic_federation_rule_id": "fdrl_test"},
        {"anthropic_workspace_id": "wrkspc_test"},
        {"openai_identity_provider_id": "idp_test"},
        {"openai_service_account_id": "svcacct_test"},
    ],
)
def test_partial_federation_config_fails_at_startup(partial):
    with pytest.raises(ValidationError, match="Workload identity federation needs"):
        _settings(**partial)


def test_gcp_identity_token_asks_the_metadata_server_for_full_claims():
    response = MagicMock(text="google-id-token\n")
    with patch(
        "app.model_providers.federation.httpx.get", return_value=response
    ) as get:
        assert federation.gcp_identity_token("https://api.example.com") == (
            "google-id-token"
        )
    _, kwargs = get.call_args
    assert kwargs["params"] == {
        "audience": "https://api.example.com",
        "format": "full",
    }
    assert kwargs["headers"] == {"Metadata-Flavor": "Google"}
    response.raise_for_status.assert_called_once()


def test_anthropic_factory_authenticates_with_workload_identity(federated_settings):
    model = ChatModelFactory().create(
        "anthropic", "claude-opus-4-8", WORKLOAD_IDENTITY_SENTINEL
    )
    assert isinstance(model, FederatedChatAnthropic)
    # Thinking config is unchanged by the auth mode.
    assert model.thinking == {"type": "adaptive", "display": "summarized"}
    for client in (model._client, model._async_client):
        assert client.api_key is None
        assert client.credentials is federation.anthropic_credentials()
        assert client.max_retries == 0


def test_openai_factory_shares_workload_identity_clients(federated_settings):
    factory = ChatModelFactory()
    first = factory.create("openai", "gpt-5", WORKLOAD_IDENTITY_SENTINEL)
    second = factory.create("openai", "gpt-5-mini", WORKLOAD_IDENTITY_SENTINEL)
    root, root_async = federation.openai_clients()
    assert isinstance(first, ResponsesChatOpenAI)
    for model in (first, second):
        assert model.root_client is root
        assert model.root_async_client is root_async
    assert root.workload_identity["identity_provider_id"] == "idp_test"
    assert root.workload_identity["service_account_id"] == "svcacct_test"
    assert root.max_retries == 0


def test_openai_workload_identity_uses_the_openai_audience():
    with patch(
        "app.model_providers.federation.gcp_identity_token",
        return_value="google-id-token",
    ) as fetch:
        provider = federation.openai_workload_identity()["provider"]
        assert provider["token_type"] == "id"
        assert provider["get_token"]() == "google-id-token"
    fetch.assert_called_once_with(federation.OPENAI_AUDIENCE)
