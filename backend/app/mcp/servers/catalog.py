"""The official MCP server catalog and provider compatibility policies.

Server entries are install templates: installing one copies its fields into a
fresh ``mcp_servers`` row. Compatibility quirks are different: the runtime
reads the current catalog and matches them dynamically by endpoint, issuer, or
advertised scopes, including for manually configured servers.

The canonical file is external (a hand-editable YAML behind a CDN,
``MCP_CATALOG_URL``) so adding a server needs neither a migration nor a
release. Caching, fallback and admin-sync mechanics live in
``app.utils.remote_catalog``; this module owns only the entry shape, the
validation rules, and the bundled snapshot.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, Field, model_validator

from app.auth.settings import auth_settings
from app.exceptions import DomainValidationError
from app.mcp.compatibility import MCPCompatibilityQuirk, bind_quirk_to_server
from app.mcp.servers.models import MCPAuthType, ServiceCredentialProvider
from app.mcp.servers.settings import mcp_server_settings
from app.utils.remote_catalog import RemoteCatalog


# The single copy of the catalog: bundled into the image as the offline
# fallback and uploaded as-is to the CDN (`MCP_CATALOG_URL`).
_BUNDLED_PATH = Path(__file__).parent / "catalog.yaml"
_HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_AUXILIA_TEMPLATE_URL = "https://your-auxilia.example.com/mcp"


def _validate_http_url(value: str, field: str = "url") -> None:
    bad_url = ValueError(f"{field} {value!r} must be an absolute http(s) URL")
    if any(character.isspace() for character in value):
        raise bad_url
    parsed = urlparse(value)
    try:
        hostname, _ = parsed.hostname, parsed.port
    except ValueError:
        raise bad_url from None
    if parsed.scheme not in ("http", "https") or not hostname:
        raise bad_url


class ServerURLOption(BaseModel):
    """One named endpoint offered by a multi-region catalog entry."""

    label: str
    url: str
    description: str | None = None

    @model_validator(mode="after")
    def validate_option(self) -> ServerURLOption:
        if not self.label.strip():
            raise ValueError("URL option label must not be empty")
        _validate_http_url(self.url, "URL option")
        return self


class OfficialServer(BaseModel):
    """One catalog entry. Mirrors the columns the create form prefills."""

    name: str
    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    icon_url: str | None = None
    description: str | None = None
    # Some products expose one MCP endpoint per customer instance. Their
    # catalog URL is an example that the admin must replace before creating the
    # workspace server.
    requires_url_configuration: bool = False
    # Named endpoints for products that host separate MCP servers by region.
    # The primary ``url`` must be one of them and remains the catalog identity.
    url_options: list[ServerURLOption] = Field(default_factory=list)
    # OAuth servers only: False means no dynamic client registration, so the
    # admin installing it must supply a static client_id/secret. Must be None
    # for non-OAuth servers (not applicable).
    supports_dcr: bool | None = None
    # OAuth servers may accept this deployment's public Client ID Metadata
    # Document instead of requiring DCR or admin-entered client credentials.
    supports_cimd: bool | None = None
    # Custom HTTP templates can prefill public header names while leaving their
    # secret values for the workspace admin to enter.
    custom_http_headers: list[str] = Field(default_factory=list)
    # Alternative machine identities explicitly supported by this endpoint.
    # An empty list means Service identity is not offered for the catalog
    # template; custom servers may choose any provider.
    service_credential_providers: list[ServiceCredentialProvider] = Field(
        default_factory=list
    )
    quirks: list[MCPCompatibilityQuirk] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entry(self) -> OfficialServer:
        if not self.name.strip():
            raise ValueError("server name must not be empty")
        _validate_http_url(self.url)
        option_urls = [option.url for option in self.url_options]
        option_labels = [option.label.casefold() for option in self.url_options]
        if len(set(option_urls)) != len(option_urls):
            raise ValueError(f"{self.name!r} has duplicate URL options")
        if len(set(option_labels)) != len(option_labels):
            raise ValueError(f"{self.name!r} has duplicate URL option labels")
        if self.url_options and self.url not in option_urls:
            raise ValueError(
                f"{self.name!r} primary url must be included in url_options"
            )
        if self.auth_type is MCPAuthType.oauth2:
            # A missing flag would silently read as "DCR works", and the admin
            # would only discover otherwise when authorization fails.
            if self.supports_dcr is None:
                raise ValueError(
                    f"{self.name!r} is an oauth2 server, so supports_dcr must be set"
                )
        elif self.supports_dcr is not None:
            raise ValueError(
                f"{self.name!r} is not an oauth2 server, so supports_dcr must be omitted"
            )
        elif self.supports_cimd is not None:
            raise ValueError(
                f"{self.name!r} is not an oauth2 server, so supports_cimd must be omitted"
            )
        if self.auth_type is MCPAuthType.custom_http:
            if not self.custom_http_headers:
                raise ValueError(
                    f"{self.name!r} uses custom_http auth, so at least one "
                    "custom_http_headers entry is required"
                )
            normalized_headers = [name.lower() for name in self.custom_http_headers]
            if len(set(normalized_headers)) != len(normalized_headers):
                raise ValueError(f"{self.name!r} has duplicate custom HTTP headers")
            for name in self.custom_http_headers:
                if not _HTTP_HEADER_NAME.fullmatch(name):
                    raise ValueError(
                        f"{self.name!r} has an invalid custom HTTP header name: {name!r}"
                    )
        elif self.custom_http_headers:
            raise ValueError(
                f"{self.name!r} is not a custom_http server, so "
                "custom_http_headers must be omitted"
            )
        if (
            ServiceCredentialProvider.custom_http_headers
            in self.service_credential_providers
        ):
            raise ValueError("custom_http_headers belongs to the custom_http auth type")
        if len(set(self.service_credential_providers)) != len(
            self.service_credential_providers
        ):
            raise ValueError(
                f"{self.name!r} has duplicate service credential providers"
            )
        quirk_names = [quirk.name for quirk in self.quirks]
        if len(set(quirk_names)) != len(quirk_names):
            raise ValueError(f"{self.name!r} has duplicate compatibility quirks")
        return self


class CatalogDocument(BaseModel):
    schema_version: Literal[1]
    servers: list[OfficialServer]

    @model_validator(mode="after")
    def entries_are_non_empty_and_unique(self) -> CatalogDocument:
        if not self.servers:
            raise ValueError("catalog has no servers")
        # URL and name are list keys for catalog templates. Configured workspace
        # instances have their own UUIDs and may reuse a template URL.
        seen_urls: set[str] = set()
        seen_names: set[str] = set()
        for server in self.servers:
            if server.name in seen_names:
                raise ValueError(f"duplicate name {server.name!r}")
            for url in {server.url, *(option.url for option in server.url_options)}:
                if url in seen_urls:
                    raise ValueError(f"duplicate url {url!r}")
                seen_urls.add(url)
            seen_names.add(server.name)
        return self


def _parse_document(text: str) -> CatalogDocument:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"catalog is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("catalog root must be a mapping")
    return CatalogDocument.model_validate(data)


def parse_catalog(text: str) -> list[OfficialServer]:
    """Parse + validate the server templates from one complete catalog."""
    return _parse_document(text).servers


def _server_quirks(
    servers: list[OfficialServer],
) -> list[MCPCompatibilityQuirk]:
    return [
        bind_quirk_to_server(quirk, url)
        for server in servers
        for url in {server.url, *(option.url for option in server.url_options)}
        for quirk in server.quirks
    ]


_catalog: RemoteCatalog[OfficialServer] = RemoteCatalog(
    # v2 adds runtime quirks to each cached server item. A new namespace keeps
    # pre-v2 Redis payloads from silently validating with empty default lists.
    prefix="mcp:catalog:v2",
    item_model=OfficialServer,
    parse=parse_catalog,
    key=lambda s: s.url,
    url=lambda: mcp_server_settings.mcp_catalog_url,
    bundled_path=_BUNDLED_PATH,
)


def bundled_catalog() -> list[OfficialServer]:
    """The snapshot shipped with the backend — the fallback of last resort."""
    return _catalog.bundled()


@lru_cache(maxsize=1)
def bundled_compatibility_quirks() -> tuple[MCPCompatibilityQuirk, ...]:
    """Compatibility fallback used before an async catalog lookup is available."""
    return tuple(_server_quirks(_catalog.bundled()))


async def get_catalog() -> list[OfficialServer]:
    """The current catalog, through memo → Redis → CDN → last_good → bundled."""
    catalog = await _catalog.get()
    frontend_url = auth_settings.FRONTEND_URL.rstrip("/")
    return [
        entry.model_copy(
            update={
                "url": f"{frontend_url}/mcp",
                "icon_url": f"{frontend_url}/logo.svg",
                "requires_url_configuration": False,
            }
        )
        if entry.url == _AUXILIA_TEMPLATE_URL
        else entry
        for entry in catalog
    ]


async def get_compatibility_quirks() -> list[MCPCompatibilityQuirk]:
    """Current catalog-managed runtime compatibility policies."""
    return _server_quirks(await _catalog.get())


async def sync_catalog() -> dict:
    """Admin-triggered refresh: force-fetch, validate, overwrite the cache.

    Unlike the lazy path this RAISES on failure (the admin pressed the button;
    they need to know) and returns the diff vs the previously served list.
    """
    if not _catalog.url:
        raise DomainValidationError(
            "No MCP_CATALOG_URL configured; this deployment uses the bundled catalog."
        )
    try:
        result = await _catalog.sync()
    except ValueError as exc:
        raise DomainValidationError(f"Catalog file is invalid: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DomainValidationError(f"Catalog fetch failed: {exc}") from exc

    return {
        "added": result.added,
        "removed": result.removed,
        "server_count": result.count,
        "fetched_at": result.fetched_at,
    }
