"""The temporary production probe must not leak normal requests or credentials."""

import json
import logging

import httpx2
import pytest

from app.mcp.client.connection import _log_non_2xx_body


@pytest.mark.parametrize("status", [200, 400, 401])
async def test_probe_logs_at_warning_without_credentials(status, caplog):
    payload = {
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "execute_sql_readonly",
            "arguments": {
                "projectId": "test-project",
                "query": "SELECT 'hello' AS greeting",
                "extra": "argument-secret",
            },
            "_meta": {"private": "metadata-secret"},
        },
    }
    request = httpx2.Request(
        "POST",
        "https://bigquery.googleapis.com/mcp",
        json=payload,
        headers={
            "Authorization": "Bearer token-secret",
            "Cookie": "cookie-secret",
            "X-Private": "header-secret",
            "MCP-Protocol-Version": "2025-11-25",
        },
    )
    response = httpx2.Response(status, request=request, text="response-secret")
    with caplog.at_level(logging.WARNING):
        await _log_non_2xx_body(response)
    assert "BQ_DIAGNOSTIC" in caplog.text
    assert "test-project" in caplog.text
    assert "2025-11-25" in caplog.text
    assert f"status={status}" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"method": "tools/call", "params": []},
        {
            "method": "tools/call",
            "params": {
                "name": "execute_sql_readonly",
                "arguments": None,
            },
        },
        {
            "method": "tools/call",
            "params": {
                "name": "execute_sql_readonly",
                "arguments": {"query": "SELECT * FROM private_table"},
            },
        },
    ],
)
async def test_other_payloads_are_silent(payload, caplog):
    request = httpx2.Request(
        "POST",
        "https://bigquery.googleapis.com/mcp",
        content=json.dumps(payload),
    )
    await _log_non_2xx_body(httpx2.Response(200, request=request))
    assert "BQ_DIAGNOSTIC" not in caplog.text


async def test_unread_stream_is_not_consumed(caplog):
    async def body():
        raise AssertionError("The diagnostic must not consume the request stream")
        yield b""

    request = httpx2.Request(
        "POST",
        "https://bigquery.googleapis.com/mcp",
        content=body(),
    )
    await _log_non_2xx_body(httpx2.Response(200, request=request))
    assert "BQ_DIAGNOSTIC" not in caplog.text
