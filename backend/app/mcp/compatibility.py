"""Declarative compatibility policies for remote MCP providers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


_HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class OAuthRedirectMode(StrEnum):
    hosted_callback = "hosted_callback"
    loopback_manual = "loopback_manual"


class OAuthRedirectStrategy(BaseModel):
    """Where an OAuth server sends the browser after authorization."""

    model_config = ConfigDict(frozen=True)

    mode: OAuthRedirectMode
    redirect_uri: str
    application_type: Literal["web", "native"]
    token_endpoint_auth_method: Literal[
        "client_secret_post", "client_secret_basic", "none"
    ]
    manual_completion_required: bool

    @model_validator(mode="after")
    def validate_strategy(self) -> OAuthRedirectStrategy:
        _absolute_http_url(self.redirect_uri, field="OAuth redirect URI")
        parsed = urlparse(self.redirect_uri)
        if self.mode is OAuthRedirectMode.loopback_manual:
            if (
                parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.port is None
                or parsed.username is not None
                or parsed.password is not None
                or not parsed.path
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "manual loopback OAuth redirects must be fixed http URLs on "
                    "127.0.0.1 with an explicit port and path"
                )
            if (
                self.application_type != "native"
                or self.token_endpoint_auth_method != "none"
                or not self.manual_completion_required
            ):
                raise ValueError(
                    "manual loopback OAuth requires a native public client and "
                    "manual completion"
                )
        elif self.manual_completion_required:
            raise ValueError("hosted OAuth callbacks cannot require manual completion")
        return self


def _absolute_http_url(value: str, *, field: str) -> str:
    parsed = urlparse(value)
    try:
        hostname, _ = parsed.hostname, parsed.port
    except ValueError:
        hostname = None
    if (
        any(character.isspace() for character in value)
        or parsed.scheme not in ("http", "https")
        or not hostname
    ):
        raise ValueError(f"{field} {value!r} must be an absolute http(s) URL")
    return value


class CompatibilityMatch(BaseModel):
    """Additional fingerprints for a policy already owned by a catalog item."""

    model_config = ConfigDict(frozen=True)

    server_urls: tuple[str, ...] = ()
    server_hostname_suffixes: tuple[str, ...] = ()
    issuers: tuple[str, ...] = ()
    advertised_scope_markers: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_matchers(self) -> CompatibilityMatch:
        for value in self.server_urls:
            _absolute_http_url(value, field="server URL")
        for value in self.issuers:
            _absolute_http_url(value, field="issuer")
        for suffix in self.server_hostname_suffixes:
            if (
                not suffix
                or suffix != suffix.lower()
                or any(character.isspace() for character in suffix)
                or "/" in suffix
            ):
                raise ValueError(
                    f"hostname suffix {suffix!r} must be a lowercase hostname"
                )
        if any(not marker.strip() for marker in self.advertised_scope_markers):
            raise ValueError("advertised scope markers must not be empty")
        return self


class OAuthCompatibility(BaseModel):
    """OAuth behavior that standards discovery cannot express correctly."""

    model_config = ConfigDict(frozen=True)

    token_endpoint_auth_method: (
        Literal["client_secret_post", "client_secret_basic", "none"] | None
    ) = None
    authorization_params: dict[str, str] = Field(default_factory=dict)
    scope: str | None = None
    redirect_strategy: OAuthRedirectStrategy | None = None

    @model_validator(mode="after")
    def validate_policy(self) -> OAuthCompatibility:
        if not (
            self.token_endpoint_auth_method
            or self.authorization_params
            or self.scope
            or self.redirect_strategy
        ):
            raise ValueError("an OAuth compatibility policy must not be empty")
        if self.scope is not None and not self.scope.strip():
            raise ValueError("OAuth scope must not be empty")
        if any(not key.strip() for key in self.authorization_params):
            raise ValueError("OAuth authorization parameter names must not be empty")
        return self


class TransportCompatibility(BaseModel):
    """HTTP transport adaptations applied by the generic MCP client."""

    model_config = ConfigDict(frozen=True)

    jsonrpc_success_statuses: tuple[int, ...] = ()
    header_csv_values: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_policy(self) -> TransportCompatibility:
        if not self.jsonrpc_success_statuses and not self.header_csv_values:
            raise ValueError("a transport compatibility policy must not be empty")
        if any(
            status < 400 or status > 599 for status in self.jsonrpc_success_statuses
        ):
            raise ValueError("JSON-RPC success statuses must be HTTP error statuses")
        for header, values in self.header_csv_values.items():
            if not _HTTP_HEADER_NAME.fullmatch(header):
                raise ValueError(f"invalid HTTP header name: {header!r}")
            if not values or any(not value.strip() for value in values):
                raise ValueError(f"header {header!r} needs non-empty CSV values")
        return self


class MCPCompatibilityQuirk(BaseModel):
    """One catalog-managed provider fingerprint and its runtime behavior."""

    model_config = ConfigDict(frozen=True)

    name: str
    match: CompatibilityMatch = Field(default_factory=CompatibilityMatch)
    oauth: OAuthCompatibility | None = None
    transport: TransportCompatibility | None = None

    @model_validator(mode="after")
    def validate_quirk(self) -> MCPCompatibilityQuirk:
        if not self.name.strip():
            raise ValueError("compatibility quirk name must not be empty")
        if self.oauth is None and self.transport is None:
            raise ValueError(
                f"compatibility quirk {self.name!r} needs an OAuth or transport policy"
            )
        return self


def bind_quirk_to_server(
    quirk: MCPCompatibilityQuirk, server_url: str
) -> MCPCompatibilityQuirk:
    """Default an item-owned policy to its URL when it declares no matcher."""

    if (
        quirk.match.server_urls
        or quirk.match.server_hostname_suffixes
        or quirk.match.issuers
        or quirk.match.advertised_scope_markers
    ):
        return quirk
    return quirk.model_copy(
        update={
            "match": quirk.match.model_copy(update={"server_urls": (server_url,)}),
        }
    )


def _issuer_key(issuer: str | None) -> str | None:
    if issuer is None:
        return None
    return issuer if issuer.endswith("/") else f"{issuer}/"


def matching_quirks(
    quirks: Sequence[MCPCompatibilityQuirk],
    *,
    server_url: str | None = None,
    issuer: str | None = None,
    advertised_scopes: Sequence[str] | None = None,
) -> list[MCPCompatibilityQuirk]:
    """Return policies matching any fingerprint known at this flow stage."""

    parsed = urlparse(server_url) if server_url is not None else None
    hostname = parsed.hostname.lower() if parsed and parsed.hostname else None
    issuer_key = _issuer_key(issuer)
    scope_set = frozenset(advertised_scopes or ())

    return [
        quirk
        for quirk in quirks
        if (server_url is not None and server_url in quirk.match.server_urls)
        or (
            hostname is not None
            and any(
                hostname.endswith(suffix)
                for suffix in quirk.match.server_hostname_suffixes
            )
        )
        or (
            issuer_key is not None
            and any(_issuer_key(value) == issuer_key for value in quirk.match.issuers)
        )
        or (
            bool(quirk.match.advertised_scope_markers)
            and quirk.match.advertised_scope_markers.issubset(scope_set)
        )
    ]
