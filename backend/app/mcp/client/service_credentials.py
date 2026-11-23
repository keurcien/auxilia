"""Pluggable machine identities for outbound MCP connections."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator, Generator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx2
from azure.identity.aio import ManagedIdentityCredential
from botocore.auth import SigV4Auth  # type: ignore[import-untyped]
from botocore.awsrequest import AWSRequest  # type: ignore[import-untyped]
from botocore.credentials import Credentials  # type: ignore[import-untyped]
from botocore.session import Session as BotocoreSession  # type: ignore[import-untyped]
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from jose import JOSEError, jwt

from app.exceptions import DomainValidationError
from app.mcp.servers.models import ServiceCredentialProvider


GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_GOOGLE_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
GITHUB_API_ROOT = "https://api.github.com"
AZURE_DEFAULT_SCOPE_SUFFIX = "/.default"


@dataclass(frozen=True)
class ServiceCredentialConfig:
    provider: ServiceCredentialProvider
    credentials_json: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedServiceCredential:
    principal: str | None
    scopes: tuple[str, ...]


def normalize_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))


def _json_object(credentials_json: str) -> dict[str, Any]:
    try:
        value = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise DomainValidationError(
            "Service credentials must contain valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise DomainValidationError("Service credentials JSON must be an object")
    return value


def _required_string(
    value: dict[str, Any], key: str, *, label: str | None = None
) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise DomainValidationError(f"{label or key} is required")
    if "\r" in raw or "\n" in raw:
        raise DomainValidationError(f"{label or key} contains invalid characters")
    return raw.strip()


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or "\r" in raw or "\n" in raw:
        raise DomainValidationError(f"{key} must be a valid string")
    return raw.strip() or None


def _https_url(value: dict[str, Any], key: str, *, label: str) -> str:
    url = _required_string(value, key, label=label)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise DomainValidationError(f"{label} must be an absolute HTTPS URL")
    return url


def _google_credentials_info(credentials_json: str) -> dict[str, Any]:
    value = _json_object(credentials_json)
    if value.get("type") != "service_account":
        raise DomainValidationError("Google credentials must be a service account key")

    # Never let an uploaded key choose an arbitrary backend destination. Google
    # keys currently contain this endpoint, but it is configuration rather than
    # signed key material and accepting it verbatim would create an SSRF seam.
    value["token_uri"] = GOOGLE_TOKEN_ENDPOINT
    return value


@dataclass(frozen=True)
class OAuthClientCredentialsConfig:
    token_url: str
    client_id: str
    client_secret: str
    token_endpoint_auth_method: str
    audience: str | None
    resource: str | None


def _oauth_client_credentials_config(
    credentials_json: str,
) -> OAuthClientCredentialsConfig:
    value = _json_object(credentials_json)
    auth_method = (
        _optional_string(value, "token_endpoint_auth_method") or "client_secret_basic"
    )
    if auth_method not in {"client_secret_basic", "client_secret_post"}:
        raise DomainValidationError(
            "Token endpoint auth method must be client_secret_basic "
            "or client_secret_post"
        )
    return OAuthClientCredentialsConfig(
        token_url=_https_url(value, "token_url", label="Token URL"),
        client_id=_required_string(value, "client_id", label="Client ID"),
        client_secret=_required_string(value, "client_secret", label="Client secret"),
        token_endpoint_auth_method=auth_method,
        audience=_optional_string(value, "audience"),
        resource=_optional_string(value, "resource"),
    )


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    installation_id: int
    private_key: str


def _github_app_config(credentials_json: str) -> GitHubAppConfig:
    value = _json_object(credentials_json)
    app_id = _required_string(value, "app_id", label="GitHub App ID")
    raw_installation_id = value.get("installation_id")
    if not isinstance(raw_installation_id, (str, int)):
        raise DomainValidationError("GitHub installation ID must be a positive integer")
    try:
        installation_id = int(raw_installation_id)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "GitHub installation ID must be a positive integer"
        ) from exc
    if installation_id <= 0:
        raise DomainValidationError("GitHub installation ID must be a positive integer")
    private_key = _required_string(value, "private_key", label="GitHub App private key")
    config = GitHubAppConfig(
        app_id=app_id,
        installation_id=installation_id,
        private_key=private_key,
    )
    _github_app_jwt(config)
    return config


def _github_app_jwt(config: GitHubAppConfig) -> str:
    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": config.app_id},
            config.private_key,
            algorithm="RS256",
        )
    except (JOSEError, ValueError, TypeError) as exc:
        raise DomainValidationError("GitHub App private key is invalid") from exc


@dataclass(frozen=True)
class AWSIAMConfig:
    region: str
    service: str
    access_key_id: str | None
    secret_access_key: str | None
    session_token: str | None


def _aws_iam_config(credentials_json: str) -> AWSIAMConfig:
    value = _json_object(credentials_json)
    access_key_id = _optional_string(value, "access_key_id")
    secret_access_key = _optional_string(value, "secret_access_key")
    if bool(access_key_id) != bool(secret_access_key):
        raise DomainValidationError(
            "AWS access key ID and secret access key must be provided together"
        )
    return AWSIAMConfig(
        region=_required_string(value, "region", label="AWS region"),
        service=_required_string(value, "service", label="AWS service"),
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=_optional_string(value, "session_token"),
    )


@dataclass(frozen=True)
class AzureManagedIdentityConfig:
    scope: str
    client_id: str | None


def _azure_managed_identity_config(
    credentials_json: str,
) -> AzureManagedIdentityConfig:
    value = _json_object(credentials_json)
    resource = _required_string(
        value, "resource", label="Azure resource App ID URI"
    ).rstrip("/")
    scope = (
        resource
        if resource.endswith(AZURE_DEFAULT_SCOPE_SUFFIX)
        else f"{resource}{AZURE_DEFAULT_SCOPE_SUFFIX}"
    )
    return AzureManagedIdentityConfig(
        scope=scope,
        client_id=_optional_string(value, "client_id"),
    )


_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_RESERVED_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _custom_headers(credentials_json: str) -> tuple[tuple[str, str], ...]:
    raw_headers = _json_object(credentials_json).get("headers")
    if not isinstance(raw_headers, list) or not raw_headers:
        raise DomainValidationError("At least one custom HTTP header is required")

    headers: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in raw_headers:
        if not isinstance(raw, dict):
            raise DomainValidationError("Each custom HTTP header must be an object")
        name = raw.get("name")
        value = raw.get("value")
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise DomainValidationError(f"Invalid HTTP header name: {name!r}")
        lowered = name.lower()
        if lowered in _RESERVED_HEADERS:
            raise DomainValidationError(
                f"HTTP header '{name}' is managed by the transport"
            )
        if lowered in seen:
            raise DomainValidationError(f"Duplicate HTTP header: {name}")
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\r" in value
            or "\n" in value
        ):
            raise DomainValidationError(f"Invalid value for HTTP header '{name}'")
        seen.add(lowered)
        headers.append((name, value))
    return tuple(headers)


def _google_credentials(
    credentials_json: str, scopes: Sequence[str]
) -> service_account.Credentials:
    normalized = normalize_scopes(scopes) or DEFAULT_GOOGLE_SCOPES
    try:
        return service_account.Credentials.from_service_account_info(
            _google_credentials_info(credentials_json),
            scopes=normalized,
        )
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "Google service account credentials are incomplete or invalid"
        ) from exc


def validate_service_credential(
    provider: ServiceCredentialProvider,
    credentials_json: str,
    scopes: Sequence[str],
) -> ValidatedServiceCredential:
    """Validate provider data without making a network request."""
    match provider:
        case ServiceCredentialProvider.google_service_account:
            credentials = _google_credentials(credentials_json, scopes)
            return ValidatedServiceCredential(
                principal=credentials.service_account_email,
                scopes=tuple(credentials.scopes or DEFAULT_GOOGLE_SCOPES),
            )
        case ServiceCredentialProvider.oauth_client_credentials:
            oauth_config = _oauth_client_credentials_config(credentials_json)
            return ValidatedServiceCredential(
                principal=oauth_config.client_id,
                scopes=normalize_scopes(scopes),
            )
        case ServiceCredentialProvider.github_app:
            github_config = _github_app_config(credentials_json)
            return ValidatedServiceCredential(
                principal=(
                    f"app:{github_config.app_id}/installation:"
                    f"{github_config.installation_id}"
                ),
                scopes=(),
            )
        case ServiceCredentialProvider.aws_iam:
            aws_config = _aws_iam_config(credentials_json)
            return ValidatedServiceCredential(
                principal=(aws_config.access_key_id or "AWS default credential chain"),
                scopes=(),
            )
        case ServiceCredentialProvider.azure_managed_identity:
            azure_config = _azure_managed_identity_config(credentials_json)
            return ValidatedServiceCredential(
                principal=(
                    azure_config.client_id or "System-assigned managed identity"
                ),
                scopes=(),
            )
        case ServiceCredentialProvider.custom_http_headers:
            headers = _custom_headers(credentials_json)
            count = len(headers)
            return ValidatedServiceCredential(
                principal=f"{count} configured HTTP header{'s' if count != 1 else ''}",
                scopes=(),
            )
        case _:
            raise DomainValidationError(
                f"Unsupported service credential provider: {provider!r}"
            )


class GoogleServiceAccountAuth(httpx2.Auth):
    """Refresh a Google service-account token and apply it as a Bearer token."""

    def __init__(self, credentials: service_account.Credentials):
        self._credentials = credentials
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        async with self._lock:
            if not self._credentials.valid:
                await asyncio.to_thread(
                    self._credentials.refresh,
                    GoogleAuthRequest(),
                )
            token = self._credentials.token
            if not isinstance(token, str) or not token:
                raise DomainValidationError(
                    "The service credential provider returned no access token"
                )
            return token

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        request.headers["Authorization"] = f"Bearer {await self._access_token()}"
        yield request


class CustomHTTPHeadersAuth(httpx2.Auth):
    """Apply a workspace-managed set of static headers to every request."""

    def __init__(self, headers: tuple[tuple[str, str], ...]):
        self._headers = headers

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response]:
        for name, value in self._headers:
            request.headers[name] = value
        yield request


class CachedBearerAuth(httpx2.Auth):
    """Fetch short-lived provider tokens once and refresh them before expiry."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh_token(self) -> tuple[str, float]:
        raise NotImplementedError

    async def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        async with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - 60:
                return self._token
            token, expires_at = await self._refresh_token()
            if not token:
                raise DomainValidationError(
                    "The service credential provider returned no access token"
                )
            self._token = token
            self._expires_at = expires_at
            return token

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        request.headers["Authorization"] = f"Bearer {await self._access_token()}"
        yield request


def _token_payload(response: httpx2.Response, provider: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx2.HTTPError, ValueError) as exc:
        raise DomainValidationError(
            f"{provider} could not issue an access token"
        ) from exc
    if not isinstance(payload, dict):
        raise DomainValidationError(f"{provider} returned an invalid token response")
    return payload


class OAuthClientCredentialsAuth(CachedBearerAuth):
    def __init__(
        self, config: OAuthClientCredentialsConfig, scopes: Sequence[str]
    ) -> None:
        super().__init__()
        self._config = config
        self._scopes = normalize_scopes(scopes)

    async def _refresh_token(self) -> tuple[str, float]:
        data: dict[str, str] = {"grant_type": "client_credentials"}
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        if self._config.audience:
            data["audience"] = self._config.audience
        if self._config.resource:
            data["resource"] = self._config.resource

        auth: httpx2.Auth | None = None
        if self._config.token_endpoint_auth_method == "client_secret_basic":
            auth = httpx2.BasicAuth(self._config.client_id, self._config.client_secret)
        else:
            data["client_id"] = self._config.client_id
            data["client_secret"] = self._config.client_secret

        try:
            async with httpx2.AsyncClient(
                timeout=15.0, follow_redirects=False
            ) as client:
                if auth is None:
                    response = await client.post(self._config.token_url, data=data)
                else:
                    response = await client.post(
                        self._config.token_url, data=data, auth=auth
                    )
        except httpx2.HTTPError as exc:
            raise DomainValidationError(
                "OAuth token endpoint could not be reached"
            ) from exc
        payload = _token_payload(response, "OAuth client credentials")
        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(token, str) or not token:
            raise DomainValidationError("OAuth token endpoint returned no access token")
        try:
            lifetime = max(float(expires_in), 60.0)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "OAuth token endpoint returned an invalid expiry"
            ) from exc
        return token, time.time() + lifetime


class GitHubAppAuth(CachedBearerAuth):
    def __init__(self, config: GitHubAppConfig) -> None:
        super().__init__()
        self._config = config

    async def _refresh_token(self) -> tuple[str, float]:
        url = (
            f"{GITHUB_API_ROOT}/app/installations/"
            f"{self._config.installation_id}/access_tokens"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_github_app_jwt(self._config)}",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        try:
            async with httpx2.AsyncClient(
                timeout=15.0, follow_redirects=False
            ) as client:
                response = await client.post(url, headers=headers)
        except httpx2.HTTPError as exc:
            raise DomainValidationError(
                "GitHub could not be reached to create an installation token"
            ) from exc
        payload = _token_payload(response, "GitHub App")
        token = payload.get("token")
        raw_expiry = payload.get("expires_at")
        if not isinstance(token, str) or not token:
            raise DomainValidationError("GitHub returned no installation access token")
        if not isinstance(raw_expiry, str):
            raise DomainValidationError(
                "GitHub returned an invalid installation token expiry"
            )
        try:
            expires_at = datetime.fromisoformat(
                raw_expiry.replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError as exc:
            raise DomainValidationError(
                "GitHub returned an invalid installation token expiry"
            ) from exc
        return token, expires_at.timestamp()


class AWSIAMAuth(httpx2.Auth):
    """Sign every MCP HTTP request with AWS Signature Version 4."""

    def __init__(self, config: AWSIAMConfig):
        self._config = config
        self._session = BotocoreSession()
        self._explicit_credentials = (
            Credentials(
                config.access_key_id,
                config.secret_access_key,
                config.session_token,
            )
            if config.access_key_id and config.secret_access_key
            else None
        )

    def _credentials(self):
        credentials = self._explicit_credentials or self._session.get_credentials()
        if credentials is None:
            raise DomainValidationError(
                "AWS default credential chain returned no credentials"
            )
        return credentials.get_frozen_credentials()

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response]:
        try:
            body = request.content
        except httpx2.RequestNotRead as exc:
            raise DomainValidationError(
                "AWS IAM cannot sign a streaming MCP request body"
            ) from exc
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=body,
            headers=dict(request.headers),
        )
        SigV4Auth(
            self._credentials(), self._config.service, self._config.region
        ).add_auth(aws_request)
        for name, value in aws_request.headers.items():
            request.headers[name] = value
        yield request


class AzureManagedIdentityAuth(CachedBearerAuth):
    def __init__(self, config: AzureManagedIdentityConfig) -> None:
        super().__init__()
        self._config = config

    async def _refresh_token(self) -> tuple[str, float]:
        credential = ManagedIdentityCredential(client_id=self._config.client_id)
        try:
            token = await credential.get_token(self._config.scope)
        except Exception as exc:
            raise DomainValidationError(
                "Azure Managed Identity could not issue an access token"
            ) from exc
        finally:
            await credential.close()
        return token.token, float(token.expires_on)


def build_service_auth(config: ServiceCredentialConfig) -> httpx2.Auth:
    """Provider registry: turn stored machine credentials into HTTP auth."""
    match config.provider:
        case ServiceCredentialProvider.google_service_account:
            return GoogleServiceAccountAuth(
                _google_credentials(config.credentials_json, config.scopes)
            )
        case ServiceCredentialProvider.oauth_client_credentials:
            return OAuthClientCredentialsAuth(
                _oauth_client_credentials_config(config.credentials_json),
                config.scopes,
            )
        case ServiceCredentialProvider.github_app:
            return GitHubAppAuth(_github_app_config(config.credentials_json))
        case ServiceCredentialProvider.aws_iam:
            return AWSIAMAuth(_aws_iam_config(config.credentials_json))
        case ServiceCredentialProvider.azure_managed_identity:
            return AzureManagedIdentityAuth(
                _azure_managed_identity_config(config.credentials_json)
            )
        case ServiceCredentialProvider.custom_http_headers:
            return CustomHTTPHeadersAuth(_custom_headers(config.credentials_json))
        case _:
            raise DomainValidationError(
                f"Unsupported service credential provider: {config.provider!r}"
            )


def service_credential_config(
    *,
    provider: ServiceCredentialProvider,
    credentials_json: str,
    scopes: Sequence[str],
) -> ServiceCredentialConfig:
    return ServiceCredentialConfig(
        provider=provider,
        credentials_json=credentials_json,
        scopes=normalize_scopes(scopes),
    )
