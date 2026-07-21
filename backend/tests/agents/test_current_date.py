"""Tests for CurrentDateMiddleware.

The middleware appends the current UTC date to the end of the system prompt
on every model call, preserving whichever content shape the caller used
(plain string vs content blocks). Date-only granularity keeps the system
prompt stable within a day so provider prompt caching is not invalidated.
"""

import pytest
from langchain_core.messages import SystemMessage

from app.agents.current_date import CurrentDateMiddleware


class _Request:
    """Minimal ModelRequest stand-in: holds a system_message, records override."""

    def __init__(self, system_message):
        self.system_message = system_message

    def override(self, **overrides):
        return _Request(overrides["system_message"])


async def _run(system_message):
    captured = {}

    async def handler(request):
        captured["message"] = request.system_message
        return "response"

    middleware = CurrentDateMiddleware()
    result = await middleware.awrap_model_call(_Request(system_message), handler)
    assert result == "response"
    return captured["message"]


@pytest.mark.asyncio
async def test_string_content_gets_suffix():
    stamped = await _run(SystemMessage("You are a helpful assistant."))
    assert isinstance(stamped.content, str)
    assert stamped.content.startswith("You are a helpful assistant.")
    assert "Current date:" in stamped.content
    assert "UTC" in stamped.content


@pytest.mark.asyncio
async def test_block_content_gets_extra_text_block():
    original = SystemMessage(content=[{"type": "text", "text": "Instructions."}])
    stamped = await _run(original)
    assert isinstance(stamped.content, list)
    assert stamped.content[0] == {"type": "text", "text": "Instructions."}
    assert stamped.content[1]["type"] == "text"
    assert "Current date:" in stamped.content[1]["text"]


@pytest.mark.asyncio
async def test_no_system_message_creates_one():
    stamped = await _run(None)
    assert isinstance(stamped, SystemMessage)
    assert stamped.content.startswith("Current date:")


@pytest.mark.asyncio
async def test_stamp_is_stable_across_calls_within_a_day():
    """Cache-safety: two calls must produce byte-identical system prompts."""
    first = await _run(SystemMessage("Instructions."))
    second = await _run(SystemMessage("Instructions."))
    assert first.content == second.content
    # No time-of-day component — only a date.
    assert ":" not in first.content.split("Current date:")[1]
