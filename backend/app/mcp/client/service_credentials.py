"""Pluggable machine identities for outbound MCP connections."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Generator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from app.exceptions import DomainValidationError
from app.mcp.servers.models import ServiceCredentialProvider


GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_GOOGLE_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


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


def _google_credentials_info(credentials_json: str) -> dict[str, Any]:
    value = _json_object(credentials_json)
    if value.get("type") != "service_account":
        raise DomainValidationError("Google credentials must be a service account key")

    # Never let an uploaded key choose an arbitrary backend destination. Google
    # keys currently contain this endpoint, but it is configuration rather than
    # signed key material and accepting it verbatim would create an SSRF seam.
    value["token_uri"] = GOOGLE_TOKEN_ENDPOINT
    return value


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
        if not isinstance(value, str) or "\r" in value or "\n" in value:
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
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        for name, value in self._headers:
            request.headers[name] = value
        yield request


def build_service_auth(config: ServiceCredentialConfig) -> httpx2.Auth:
    """Provider registry: turn stored machine credentials into HTTP auth."""
    match config.provider:
        case ServiceCredentialProvider.google_service_account:
            return GoogleServiceAccountAuth(
                _google_credentials(config.credentials_json, config.scopes)
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
