import json
from types import SimpleNamespace

import pytest

from app.adapters.stream.adapter import AISDKStreamAdapter


def _parse_sse(event: str) -> dict | None:
    payload = event.removeprefix("data: ").strip()
    if payload == "[DONE]":
        return None
    return json.loads(payload)


async def _event_stream(events: list[dict]):
    for event in events:
        yield event


@pytest.mark.asyncio
async def test_stream_adapter_adds_auxilia_provider_metadata_for_model_tool_events():
    adapter = AISDKStreamAdapter(
        message_id="msg-1",
        tool_ui_metadata={
            "charts_render_pie_chart": {
                "mcp_app_resource_uri": "ui://chart/pie",
                "mcp_server_id": "server-1",
            }
        },
    )

    chunk = SimpleNamespace(
        tool_call_chunks=[
            {
                "id": "tool-call-1",
                "name": "charts_render_pie_chart",
                "args": "{\"values\": [1,2,3]}",
                "index": 0,
            }
        ],
        content=None,
    )
    output = SimpleNamespace(
        tool_calls=[
            {
                "id": "tool-call-1",
                "name": "charts_render_pie_chart",
                "args": {"values": [1, 2, 3]},
            }
        ]
    )

    emitted = [event async for event in adapter.stream(_event_stream([
        {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
        {"event": "on_chat_model_end", "data": {"output": output}},
    ]))]

    payloads = [payload for payload in (_parse_sse(event)
                                        for event in emitted) if payload]

    start_event = next(
        payload for payload in payloads if payload["type"] == "tool-input-start"
    )
    available_event = next(
        payload for payload in payloads if payload["type"] == "tool-input-available"
    )

    expected_auxilia = {
        "mcpAppResourceUri": "ui://chart/pie",
        "mcpServerId": "server-1",
    }
    assert start_event["providerMetadata"]["auxilia"] == expected_auxilia
    assert available_event["providerMetadata"]["auxilia"] == expected_auxilia


@pytest.mark.asyncio
async def test_stream_adapter_adds_auxilia_provider_metadata_for_tool_start_events():
    adapter = AISDKStreamAdapter(
        message_id="msg-1",
        tool_ui_metadata={
            "charts_render_funnel_chart": {
                "mcp_app_resource_uri": "ui://chart/funnel",
                "mcp_server_id": "server-2",
            }
        },
    )

    emitted = [event async for event in adapter.stream(_event_stream([
        {
            "event": "on_tool_start",
            "name": "charts_render_funnel_chart",
            "run_id": "fallback-run-id",
            "data": {
                "input": {
                    "runtime": SimpleNamespace(tool_call_id="tool-call-2"),
                    "labels": ["A", "B"],
                }
            },
        }
    ]))]

    payloads = [payload for payload in (_parse_sse(event)
                                        for event in emitted) if payload]

    start_event = next(
        payload for payload in payloads if payload["type"] == "tool-input-start"
    )
    available_event = next(
        payload for payload in payloads if payload["type"] == "tool-input-available"
    )

    expected_auxilia = {
        "mcpAppResourceUri": "ui://chart/funnel",
        "mcpServerId": "server-2",
    }
    assert start_event["providerMetadata"]["auxilia"] == expected_auxilia
    assert available_event["providerMetadata"]["auxilia"] == expected_auxilia
