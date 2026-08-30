"""`OAUTH_QUIRKS` — the per-provider OAuth deviations, in one table.

They used to be four inline conditionals in two layers, and the Supabase one
existed twice with *different match keys* (issuer in the provider, server URL in
the callback handler), so the two copies could disagree about which servers they
covered (design review §4.1). One table, matched on either key, is what makes
the callback handler's copy deletable.
"""

from unittest.mock import AsyncMock

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata

from app.mcp.client.auth import (
    WebOAuthClientProvider,
    build_oauth_client_metadata,
    quirk_authorization_params,
    quirk_scope,
    quirk_token_endpoint_auth_method,
    resolve_quirks,
)


SUPABASE_URL = "https://mcp.supabase.com/mcp"
SUPABASE_ISSUER = "https://api.supabase.com/"
GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"


def test_an_unknown_server_matches_nothing():
    assert (
        resolve_quirks(
            server_url="https://mcp.notion.com/mcp", issuer="https://notion.so/"
        )
        == []
    )
    assert quirk_token_endpoint_auth_method(server_url="https://mcp.notion.com") is None
    assert quirk_authorization_params(issuer="https://notion.so/") == {}
    assert quirk_scope(server_url="https://mcp.notion.com") is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"server_url": SUPABASE_URL},
        {"issuer": SUPABASE_ISSUER},
        {"server_url": SUPABASE_URL, "issuer": SUPABASE_ISSUER},
    ],
    ids=["by-url", "by-issuer", "by-both"],
)
def test_either_key_matches_the_same_quirk(kwargs):
    """The point of the consolidation: the URL-only moment (the OAuth callback,
    before any discovery) and the issuer-only moment (a provider that has
    discovered metadata) now reach the same row."""
    assert quirk_token_endpoint_auth_method(**kwargs) == "client_secret_post"


def test_google_asks_for_a_refresh_token():
    params = quirk_authorization_params(issuer="https://accounts.google.com/")

    assert params == {"access_type": "offline", "prompt": "consent"}


def test_gmail_scopes_are_fixed_because_the_server_advertises_none():
    scope = quirk_scope(server_url=GMAIL_URL)

    assert scope is not None
    assert "https://www.googleapis.com/auth/gmail.modify" in scope


async def test_initialize_applies_the_quirk_by_url_alone():
    """What lets `handle_oauth_callback` drop its own copy: the exchange runs on
    a fresh provider whose metadata discovery has not happened, so only the URL
    is known — and the quirk still lands, on the stored client_info *and* the
    metadata the client_info is rebuilt from.
    """
    stored = OAuthClientInformationFull(
        client_id="abc",
        client_secret="xyz",
        redirect_uris=["https://auxilia.example.com/callback"],
        token_endpoint_auth_method="client_secret_basic",
    )
    storage = AsyncMock()
    storage.get_tokens.return_value = None
    storage.get_client_info.return_value = stored
    storage.get_oauth_metadata.return_value = None

    provider = WebOAuthClientProvider(
        server_url=SUPABASE_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=storage,
    )
    await provider._initialize()

    assert provider.context.client_info.token_endpoint_auth_method == (
        "client_secret_post"
    )
    assert provider.context.client_metadata.token_endpoint_auth_method == (
        "client_secret_post"
    )


async def test_initialize_leaves_an_unquirked_server_alone():
    storage = AsyncMock()
    storage.get_tokens.return_value = None
    storage.get_client_info.return_value = None
    storage.get_oauth_metadata.return_value = OAuthMetadata(
        issuer="https://notion.so/",
        authorization_endpoint="https://notion.so/authorize",
        token_endpoint="https://notion.so/token",
    )

    provider = WebOAuthClientProvider(
        server_url="https://mcp.notion.com/mcp",
        client_metadata=build_oauth_client_metadata(),
        storage=storage,
    )
    await provider._initialize()

    # build_oauth_client_metadata's own default, untouched.
    assert provider.context.client_metadata.token_endpoint_auth_method == (
        "client_secret_post"
    )
    assert provider.context.client_info is None
