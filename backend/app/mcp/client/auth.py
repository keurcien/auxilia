import secrets
from urllib.parse import urlencode, urljoin

import httpx
from mcp.client.auth import OAuthClientProvider, OAuthFlowError, PKCEParameters
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from app.mcp.client.exceptions import OAuthAuthorizationRequired

import logging

logger = logging.getLogger(__name__)

def build_oauth_client_metadata(mcp_server: dict) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="auxilia",
        redirect_uris=[
            AnyUrl(f"http://localhost:8000/mcp-servers/{mcp_server.id}/oauth/callback")
        ],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="user",
    )


class ServerlessOAuthProvider(OAuthClientProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _initialize(self):
        """Initialize and properly set token expiry from stored tokens."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = await self.context.storage.get_client_info()

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = await self.context.storage.get_oauth_metadata()
        
        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)
            
        self._initialized = True

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

        # Include resource param if needed (SDK Logic)
        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            print("scope", self.context.client_metadata)
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
            self.context.oauth_metadata = await self.context.storage.get_oauth_metadata()

        # Recover Verifier
        verifier = await self.context.storage.get_verifier(state)

        if not verifier:
            raise OAuthFlowError("Session expired or invalid state")

        # Use the SDK's protected method to finish the exchange
        # This handles the HTTP request, token parsing, and storage writing

        token_request = await self._exchange_token_authorization_code(
            auth_code=code, code_verifier=verifier
        )

        # Execute the request (since _exchange... returns a Request object)
        async with httpx.AsyncClient() as client:
            response = await client.send(token_request)
            print(response)
            await self._handle_token_response(response)

        await self.context.storage.delete_verifier(state)
