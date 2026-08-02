"""The official MCP server catalog — the curated list shown in "add server".

Reference data only: an entry is a template, and installing one copies its
fields into a fresh ``mcp_servers`` row. Nothing links back to the catalog, so
``url`` is the identity key — it is what decides whether a server already
appears as installed.

The canonical file is external (a hand-editable YAML behind a CDN,
``MCP_CATALOG_URL``) so adding a server needs neither a migration nor a
release. Caching, fallback and admin-sync mechanics live in
``app.utils.remote_catalog``; this module owns only the entry shape, the
validation rules, and the bundled snapshot.
"""

import logging
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, model_validator

from app.exceptions import DomainValidationError
from app.mcp.servers.models import MCPAuthType
from app.mcp.servers.settings import mcp_server_settings
from app.utils.remote_catalog import RemoteCatalog


logger = logging.getLogger(__name__)

_BUNDLED_PATH = Path(__file__).parent / "catalog.yaml"


class OfficialServer(BaseModel):
    """One catalog entry. Mirrors the columns the create form prefills."""

    name: str
    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    icon_url: str | None = None
    description: str | None = None
    # OAuth servers only: False means no dynamic client registration, so the
    # admin installing it must supply a static client_id/secret. Must be None
    # for non-OAuth servers (not applicable).
    supports_dcr: bool | None = None

    @model_validator(mode="after")
    def validate_entry(self) -> "OfficialServer":
        if not self.name.strip():
            raise ValueError("server name must not be empty")
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"url {self.url!r} must be an absolute http(s) URL")
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
        return self


class CatalogDocument(BaseModel):
    schema_version: Literal[1]
    servers: list[OfficialServer]

    @model_validator(mode="after")
    def servers_non_empty_and_unique(self) -> "CatalogDocument":
        if not self.servers:
            raise ValueError("catalog has no servers")
        # url is the identity key (is_installed matches on it); name is the
        # frontend's list key. Both must be unique.
        seen_urls: set[str] = set()
        seen_names: set[str] = set()
        for server in self.servers:
            if server.url in seen_urls:
                raise ValueError(f"duplicate url {server.url!r}")
            if server.name in seen_names:
                raise ValueError(f"duplicate name {server.name!r}")
            seen_urls.add(server.url)
            seen_names.add(server.name)
        return self


def parse_catalog(text: str) -> list[OfficialServer]:
    """Parse + validate a catalog YAML. Raises ValueError on any problem —
    callers treat the file as all-or-nothing."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"catalog is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("catalog root must be a mapping")
    return CatalogDocument.model_validate(data).servers


_catalog: RemoteCatalog[OfficialServer] = RemoteCatalog(
    prefix="mcp:catalog",
    item_model=OfficialServer,
    parse=parse_catalog,
    key=lambda s: s.url,
    url=lambda: mcp_server_settings.mcp_catalog_url,
    bundled_path=_BUNDLED_PATH,
)


def bundled_catalog() -> list[OfficialServer]:
    """The snapshot shipped with the backend — the fallback of last resort."""
    return _catalog.bundled()


async def get_catalog() -> list[OfficialServer]:
    """The current catalog, through memo → Redis → CDN → last_good → bundled."""
    return await _catalog.get()


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
