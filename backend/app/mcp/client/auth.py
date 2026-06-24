import logging
import secrets
from urllib.parse import urlencode, urljoin

import httpx
from mcp.client.auth import OAuthClientProvider, OAuthFlowError, PKCEParameters
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_registration_request,
    create_oauth_metadata_request,
    get_client_metadata_scopes,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import AnyHttpUrl, AnyUrl

from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.settings import app_settings


logger = logging.getLogger(__name__)


def build_oauth_client_metadata() -> OAuthClientMetadata:
    """Static OAuth client-registration metadata for auxilia.

    Scopes are intentionally omitted: they are discovered per-server from the
    Protected Resource Metadata (RFC 9728 ``scopes_supported``) during
    authorization, so there is nothing server-specific to configure here.
    """
    return OAuthClientMetadata(
        client_name="auxilia",
        redirect_uris=[
            AnyUrl(f"{app_settings.backend_url}/mcp-servers/oauth/callback")
        ],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=None,
    )


class WebOAuthClientProvider(OAuthClientProvider):
    """Web OAuth client provider for MCP servers. Idea is to stick as close as possible to the official MCP SDK."""

    def __init__(
        self,
        *args,
        client_id: str | None = None,
        client_secret: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._client_id = client_id
        self._client_secret = client_secret

    async def _initialize(self):
        """Initialize and properly set token expiry from stored tokens."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = await self.context.storage.get_client_info()

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )

        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.issuer
            == AnyHttpUrl("https://api.supabase.com/")
        ):
            logger.debug("Setting token endpoint auth method to client_secret_post")
            self.context.client_info.token_endpoint_auth_method = "client_secret_post"

        if (
            not self.context.client_info
            and self.context.client_metadata
            and self._client_id
        ):
            self.context.client_info = OAuthClientInformationFull(
                client_id=self._client_id,
                client_secret=self._client_secret,
                **self.context.client_metadata.model_dump(),
            )

        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)

        self._initialized = True

    async def persist_client_info(self) -> None:
        """Persist static client registration to storage so the OAuth callback
        and the refresh path — separate requests with fresh providers — can
        recover client_id/secret. No-op when there are no static credentials
        (such servers register dynamically and persist during authorization)."""
        if not self._client_id:
            return
        await self.context.storage.set_client_info(
            OAuthClientInformationFull(
                client_id=self._client_id,
                client_secret=self._client_secret,
                **self.context.client_metadata.model_dump(),
            )
        )

    async def initiate_authorization(self) -> None:
        """Start the OAuth flow explicitly, without calling a business tool to
        provoke a 401.

        Discovers OAuth metadata the same way the SDK's ``async_auth_flow``
        does on a 401 — RFC 9728 Protected Resource Metadata, then RFC 8414 /
        OIDC Authorization Server Metadata — applies the discovered scopes,
        then builds the authorization URL (which raises
        ``OAuthAuthorizationRequired`` via the overridden
        ``_perform_authorization_code_grant``).

        The discovery GETs run on a plain ``httpx.AsyncClient`` (no MCP
        session, no anyio task group), so the resulting exception propagates
        on the normal request stack instead of wrapped in an ``ExceptionGroup``.

        Mirrors the 401 branch of ``OAuthClientProvider.async_auth_flow``
        (PRM -> AS metadata -> scope selection -> DCR -> authorize). The SDK
        only exposes that sequence as inlined generator code plus the public
        helpers in ``mcp.client.auth.utils``, so this rebuilds the orchestration
        on those helpers; keep it in sync with the SDK flow on upgrades.
        """
        if not self._initialized:
            await self._initialize()

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # Step 1: Protected Resource Metadata (path-based then root well-known).
            for url in build_protected_resource_metadata_discovery_urls(
                None, self.context.server_url
            ):
                response = await client.send(create_oauth_metadata_request(url))
                prm = await handle_protected_resource_response(response)
                if prm:
                    self.context.protected_resource_metadata = prm
                    self.context.auth_server_url = str(prm.authorization_servers[0])
                    break

            # Step 2: Authorization Server Metadata (RFC 8414 / OIDC fallbacks).
            for url in build_oauth_authorization_server_metadata_discovery_urls(
                self.context.auth_server_url, self.context.server_url
            ):
                response = await client.send(create_oauth_metadata_request(url))
                ok, asm = await handle_auth_metadata_response(response)
                if ok and asm:
                    self.context.oauth_metadata = asm
                    break
                if not ok:
                    break

            # Step 3: scope selection — PRM scopes_supported if advertised,
            # otherwise no scope param (the server omits it, e.g. Notion).
            discovered_scopes = get_client_metadata_scopes(
                None,
                self.context.protected_resource_metadata,
                self.context.oauth_metadata,
            )
            if discovered_scopes:
                self.context.client_metadata.scope = discovered_scopes

            # Step 4: ensure a registered client. Static credentials (e.g.
            # Google) are loaded into client_info by _initialize; otherwise
            # register dynamically per RFC 7591 (e.g. Notion).
            if not self.context.client_info:
                registration_response = await client.send(
                    create_client_registration_request(
                        self.context.oauth_metadata,
                        self.context.client_metadata,
                        self.context.get_authorization_base_url(
                            self.context.server_url
                        ),
                    )
                )
                self.context.client_info = await handle_registration_response(
                    registration_response
                )

        if not self.context.client_info:
            raise OAuthFlowError("No client info available for authorization")

        # Persist client_info so the OAuth callback (a separate HTTP request with
        # a fresh provider) and the refresh path (probe_mcp_server) can recover
        # the client_id/secret from storage. connect_to_server persists it on its
        # own path; the explicit flow skips connect_to_server, so persist it here.
        await self.context.storage.set_client_info(self.context.client_info)

        # Builds the authorization URL and raises OAuthAuthorizationRequired.
        # protected_resource_metadata is set, so should_include_resource_param()
        # is True and the RFC 8707 resource param is included.
        await self._perform_authorization_code_grant()

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """
        Overrides the SDK method to support serverless flows.
        Instead of waiting for a callback, it saves state to Redis and raises an exception.
        """

        if self.context.oauth_metadata:
            await self.context.storage.set_oauth_metadata(self.context.oauth_metadata)

        # 1. Standard SDK Validation
        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URIs provided")

        # 2. Determine Auth Endpoint (Standard SDK Logic)
        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.authorization_endpoint
        ):
            auth_endpoint = str(self.context.oauth_metadata.authorization_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(
                self.context.server_url
            )
            auth_endpoint = urljoin(auth_base_url, "/authorize")

        if not self.context.client_info:
            raise OAuthFlowError("No client info available")

        # 3. Generate State & PKCE
        pkce_params = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)

        await self.context.storage.set_verifier(state, pkce_params.code_verifier)

        auth_params = {
            "response_type": "code",
            "client_id": self.context.client_info.client_id,
            "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
            "state": state,
            "code_challenge": pkce_params.code_challenge,
            "code_challenge_method": "S256",
        }

        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.issuer
            == AnyHttpUrl("https://accounts.google.com/")
        ):
            auth_params["access_type"] = "offline"
            auth_params["prompt"] = "consent"

        # Include resource param if needed (SDK Logic)
        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            auth_params["scope"] = self.context.client_metadata.scope

        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"

        raise OAuthAuthorizationRequired(authorization_url)

    # --- HELPER FOR PHASE 2 ---
    async def manual_exchange(self, code: str, state: str):
        """
        Called by the /callback endpoint to finish the job.
        """
        # Restore client_info from storage if missing
        if not self.context.client_info:
            self.context.client_info = await self.context.storage.get_client_info()

        if not self.context.client_info:
            raise OAuthFlowError("Client info not found in storage")

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )

        # Recover Verifier
        verifier = await self.context.storage.get_verifier(state)

        if not verifier:
            raise OAuthFlowError("Session expired or invalid state")

        # Use the SDK's protected method to finish the exchange
        # This handles the HTTP request, token parsing, and storage writing

        token_request = await self._exchange_token_authorization_code(
            auth_code=code, code_verifier=verifier
        )

        token_request.headers["Accept"] = "application/json"

        # Execute the request (since _exchange... returns a Request object)
        async with httpx.AsyncClient() as client:
            response = await client.send(token_request)
            await self._handle_token_response(response)

        await self.context.storage.delete_verifier(state)
