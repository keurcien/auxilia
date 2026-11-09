"""Workload identity federation: keyless Anthropic and OpenAI authentication.

On GCP (Cloud Run, GKE, Compute Engine) the backend's service account gets a
Google ID token from the metadata server; Anthropic and OpenAI exchange it for
short-lived access tokens, so no provider API key is stored or rotated. Each
provider's federation (rule / mapping) must match the token's claims; the IDs
come from ModelProviderSettings.

The SDKs own the exchange and the token refresh. This module only supplies
the Google identity token and builds the credentials once per process, so
token caches and HTTP connections are shared across model instances.
"""

from functools import lru_cache

import httpx
from anthropic.lib.credentials import WorkloadIdentityCredentials
from openai import AsyncOpenAI, OpenAI
from openai.auth import WorkloadIdentity

from app.model_providers.settings import model_provider_settings

ANTHROPIC_AUDIENCE = "https://api.anthropic.com"
OPENAI_AUDIENCE = "https://api.openai.com/v1"

_METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1"
    "/instance/service-accounts/default/identity"
)


def gcp_identity_token(audience: str) -> str:
    """Google ID token of the attached service account, for `audience`.

    `format=full` adds the `email` claim, so a federation rule can match the
    service account's email and not only its numeric `sub`. (openai's own
    `gcp_id_token_provider` omits it, hence this helper for both SDKs.)
    """
    response = httpx.get(
        _METADATA_IDENTITY_URL,
        params={"audience": audience, "format": "full"},
        headers={"Metadata-Flavor": "Google"},
        timeout=10,
    )
    response.raise_for_status()
    token = response.text.strip()
    if not token:
        raise RuntimeError("The GCP metadata server returned an empty identity token")
    return token


@lru_cache(maxsize=1)
def anthropic_credentials() -> WorkloadIdentityCredentials:
    """Anthropic credentials provider. Each client wraps it in its own token
    cache; sharing the provider shares its HTTP client for the exchange."""
    settings = model_provider_settings
    return WorkloadIdentityCredentials(
        identity_token_provider=lambda: gcp_identity_token(ANTHROPIC_AUDIENCE),
        federation_rule_id=settings.anthropic_federation_rule_id,
        organization_id=settings.anthropic_organization_id,
        service_account_id=settings.anthropic_service_account_id,
        workspace_id=settings.anthropic_workspace_id,
    )


def openai_workload_identity() -> WorkloadIdentity:
    settings = model_provider_settings
    return {
        "identity_provider_id": settings.openai_identity_provider_id,
        "service_account_id": settings.openai_service_account_id,
        "provider": {
            "token_type": "id",
            "get_token": lambda: gcp_identity_token(OPENAI_AUDIENCE),
        },
    }


@lru_cache(maxsize=1)
def openai_clients() -> tuple[OpenAI, AsyncOpenAI]:
    """Shared OpenAI clients authenticated by workload identity: one access
    token for every model instance. Same options as the clients LangChain
    builds from an API key in ChatModelFactory: max_retries=0 (retrying is
    owned by ModelRetryMiddleware) and no request timeout."""
    identity = openai_workload_identity()
    return (
        OpenAI(workload_identity=identity, max_retries=0, timeout=None),
        AsyncOpenAI(workload_identity=identity, max_retries=0, timeout=None),
    )
