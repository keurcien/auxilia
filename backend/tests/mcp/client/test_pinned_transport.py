"""The pin changes routing while preserving the MCP origin and TLS identity."""

from ipaddress import ip_address

import httpx2
import pytest
from pydantic import ValidationError

from app.mcp.client.connection import _logging_http_client_factory
from app.mcp.client.pinned_transport import PinnedBigQueryTransport
from app.settings import AppSettings, app_settings


async def test_pin_preserves_host_sni_body_and_original_request():
    seen = []

    async def receive(request):
        seen.append(request)
        return httpx2.Response(200, json={})

    transport = PinnedBigQueryTransport("172.217.20.42")
    await transport.inner.aclose()
    transport.inner = httpx2.MockTransport(receive)
    request = httpx2.Request(
        "POST",
        "https://bigquery.googleapis.com/mcp",
        json={"method": "tools/list"},
        headers={"Authorization": "Bearer test"},
        extensions={"timeout": {"connect": 3}},
    )
    async with transport:
        await transport.handle_async_request(request)
    forwarded = seen[0]
    assert forwarded.url.host == "172.217.20.42"
    assert forwarded.headers["host"] == "bigquery.googleapis.com"
    assert forwarded.extensions["sni_hostname"] == "bigquery.googleapis.com"
    assert forwarded.extensions["timeout"] == {"connect": 3}
    assert forwarded.headers["authorization"] == "Bearer test"
    assert await forwarded.aread() == request.content
    assert request.url.host == "bigquery.googleapis.com"
    assert "sni_hostname" not in request.extensions


async def test_factory_pins_only_bigquery_and_preserves_defaults(monkeypatch):
    monkeypatch.setattr(app_settings, "mcp_bigquery_pinned_ip", None)
    async with _logging_http_client_factory() as normal:
        default_timeout = normal.timeout
        default_follow_redirects = normal.follow_redirects
        assert not isinstance(
            normal._transport_for_url(
                httpx2.URL("https://bigquery.googleapis.com/mcp")
            ),
            PinnedBigQueryTransport,
        )
    monkeypatch.setattr(
        app_settings, "mcp_bigquery_pinned_ip", ip_address("172.217.20.42")
    )
    async with _logging_http_client_factory() as pinned:
        assert pinned.timeout == default_timeout
        assert pinned.follow_redirects == default_follow_redirects
        assert isinstance(
            pinned._transport_for_url(
                httpx2.URL("https://bigquery.googleapis.com/mcp")
            ),
            PinnedBigQueryTransport,
        )
        for url in (
            "https://accounts.google.com/",
            "https://mcp.slack.com/mcp",
            "https://bigquery.googleapis.com.example.org/mcp",
        ):
            assert not isinstance(
                pinned._transport_for_url(httpx2.URL(url)), PinnedBigQueryTransport
            )


@pytest.mark.parametrize(
    "value", [None, "", " \t ", "172.217.20.42", " 172.217.20.42 ", "::1", " ::1 "]
)
def test_pin_setting(value):
    settings = AppSettings(_env_file=None, mcp_bigquery_pinned_ip=value)
    normalized = value.strip() if isinstance(value, str) else value
    assert settings.mcp_bigquery_pinned_ip == (
        ip_address(normalized) if normalized else None
    )


def test_pin_rejects_hostname():
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, mcp_bigquery_pinned_ip="example.com")
