"""Tests for the official MCP server catalog (app/mcp/servers/catalog.py).

Validation is all-or-nothing: one bad entry fails the whole file so a broken CDN
upload can never half-apply — the deployment keeps serving the last good copy.
"""

from __future__ import annotations

import pytest

from app.mcp.servers.catalog import (
    OfficialServer,
    bundled_catalog,
    parse_catalog,
)
from app.mcp.servers.models import MCPAuthType


VALID_DOC = """
schema_version: 1
servers:
  - name: Notion
    url: https://mcp.notion.com/mcp
    auth_type: oauth2
    icon_url: https://cdn.example.com/notion.png
    supports_dcr: true
    description: Talk to your Notion workspace.
  - name: DeepWiki
    url: https://mcp.deepwiki.com/mcp
    auth_type: none
"""


def test_parse_valid_document():
    servers = parse_catalog(VALID_DOC)
    assert [s.name for s in servers] == ["Notion", "DeepWiki"]
    assert servers[0].auth_type is MCPAuthType.oauth2
    assert servers[0].supports_dcr is True
    # Optional fields default rather than failing — a minimal entry is legal.
    assert servers[1].icon_url is None
    assert servers[1].description is None
    assert servers[1].supports_dcr is None


def test_auth_type_defaults_to_none():
    servers = parse_catalog(
        "schema_version: 1\nservers:\n  - name: X\n    url: https://x.example.com/mcp\n"
    )
    assert servers[0].auth_type is MCPAuthType.none


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("schema_version: 2\nservers: []", "schema_version"),
        ("schema_version: 1\nservers: []", "no servers"),
        ("- just\n- a list", "mapping"),
        ("{invalid yaml: [", "not valid YAML"),
        (
            VALID_DOC + "  - name: Notion Again\n"
            "    url: https://mcp.notion.com/mcp\n"
            "    auth_type: none\n",
            "duplicate url",
        ),
        (
            VALID_DOC + "  - name: Notion\n"
            "    url: https://other.example.com/mcp\n"
            "    auth_type: none\n",
            "duplicate name",
        ),
        (
            "schema_version: 1\nservers:\n  - name: X\n    url: not-a-url\n",
            "absolute http",
        ),
        # netloc alone would accept these: a hostless authority, an invalid
        # port, and embedded whitespace.
        (
            "schema_version: 1\nservers:\n  - name: X\n    url: 'https://:443'\n",
            "absolute http",
        ),
        (
            "schema_version: 1\nservers:\n"
            "  - name: X\n    url: 'https://x.example.com:bad/mcp'\n",
            "absolute http",
        ),
        (
            "schema_version: 1\nservers:\n"
            "  - name: X\n    url: 'https://x.example .com/mcp'\n",
            "absolute http",
        ),
        (
            "schema_version: 1\nservers:\n"
            "  - name: X\n    url: https://x.example.com/mcp\n"
            "    auth_type: bearer\n",
            "auth_type",
        ),
        # A missing supports_dcr would read as "DCR works", so a non-DCR server
        # would only fail when a user tries to authorize it.
        (
            "schema_version: 1\nservers:\n"
            "  - name: X\n    url: https://x.example.com/mcp\n"
            "    auth_type: oauth2\n",
            "supports_dcr must be set",
        ),
        # ...and the flag is meaningless without OAuth, so it must be omitted.
        (
            "schema_version: 1\nservers:\n"
            "  - name: X\n    url: https://x.example.com/mcp\n"
            "    auth_type: api_key\n    supports_dcr: true\n",
            "supports_dcr must be omitted",
        ),
        (
            "schema_version: 1\nservers:\n"
            "  - name: '  '\n    url: https://x.example.com/mcp\n",
            "must not be empty",
        ),
    ],
)
def test_parse_rejects_bad_documents(text: str, match: str):
    with pytest.raises(ValueError, match=match):
        parse_catalog(text)


def test_bundled_snapshot_is_valid():
    servers = bundled_catalog()
    assert len(servers) >= 1
    assert all(isinstance(s, OfficialServer) for s in servers)
    # The snapshot must still carry the servers the dropped table used to seed.
    urls = {s.url for s in servers}
    assert {
        "https://mcp.notion.com/mcp",
        "https://mcp.slack.com/mcp",
        "https://mcp.deepwiki.com/mcp",
        "https://drivemcp.googleapis.com/mcp/v1",
    } <= urls
