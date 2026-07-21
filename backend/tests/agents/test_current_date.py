"""Tests for CurrentDateMiddleware.

The middleware appends a date frozen at construction (the thread's creation
date) to the end of the system prompt on every model call, preserving
whichever content shape the caller used (plain string vs content blocks).
The frozen stamp keeps the system prompt byte-identical for the thread's
lifetime, so provider prompt caches (multi-day on DeepSeek) never see the
prefix mutate.
"""

from datetime import UTC, datetime

import pytest
from langchain_core.messages import SystemMessage

from app.agents.current_date import CurrentDateMiddleware


CREATED_AT = datetime(2026, 7, 21, 14, 32, tzinfo=UTC)


class _Request:
    """Minimal ModelRequest stand-in: holds a system_message, records override."""

    def __init__(self, system_message):
        self.system_message = system_message

    def override(self, **overrides):
        return _Request(overrides["system_message"])


async def _run(system_message, middleware=None):
    captured = {}

    async def handler(request):
        captured["message"] = request.system_message
        return "response"

    middleware = middleware or CurrentDateMiddleware(CREATED_AT)
    result = await middleware.awrap_model_call(_Request(system_message), handler)
    assert result == "response"
    return captured["message"]


@pytest.mark.asyncio
async def test_string_content_gets_suffix():
    stamped = await _run(SystemMessage("You are a helpful assistant."))
    assert stamped.content == (
        "You are a helpful assistant.\n\nCurrent date: Tuesday, July 21, 2026 (UTC)"
    )


@pytest.mark.asyncio
async def test_block_content_gets_extra_text_block():
    original = SystemMessage(content=[{"type": "text", "text": "Instructions."}])
    stamped = await _run(original)
    assert isinstance(stamped.content, list)
    assert stamped.content[0] == {"type": "text", "text": "Instructions."}
    assert stamped.content[1] == {
        "type": "text",
        "text": "Current date: Tuesday, July 21, 2026 (UTC)",
    }


@pytest.mark.asyncio
async def test_no_system_message_creates_one():
    stamped = await _run(None)
    assert isinstance(stamped, SystemMessage)
    assert stamped.content == "Current date: Tuesday, July 21, 2026 (UTC)"


@pytest.mark.asyncio
async def test_stamp_is_frozen_at_construction():
    """Cache-safety: the stamp comes from the given date, never from now()."""
    middleware = CurrentDateMiddleware(datetime(2025, 1, 1, tzinfo=UTC))
    first = await _run(SystemMessage("Instructions."), middleware)
    second = await _run(SystemMessage("Instructions."), middleware)
    assert first.content == second.content
    assert "Wednesday, January 01, 2025" in first.content
    # Date only — no time-of-day component in the stamp.
    assert ":" not in first.content.split("Current date:")[1]
