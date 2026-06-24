"""Tests for tools/list pagination in app/mcp/servers/service.py.

`_list_all_tools` must not hang on a misbehaving server: a repeated or cyclic
`nextCursor` is detected, and a runaway page count is capped.
"""

from __future__ import annotations

import pytest

from app.exceptions import DomainError
from app.mcp.servers import service


class _Resp:
    def __init__(self, tools, next_cursor):
        self.tools = tools
        self.nextCursor = next_cursor


class _SeqSession:
    """Returns queued responses in order, recording the cursors it was given."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.cursors_seen = []

    async def list_tools(self, cursor=None):
        self.cursors_seen.append(cursor)
        return self._responses.pop(0)


class _CursorSession:
    """Returns next_cursors from a fixed sequence (one per call)."""

    def __init__(self, next_cursors):
        self._next_cursors = list(next_cursors)
        self.call_count = 0

    async def list_tools(self, cursor=None):
        nxt = self._next_cursors[self.call_count]
        self.call_count += 1
        return _Resp([object()], nxt)


async def test_collects_all_pages_until_falsy_cursor():
    session = _SeqSession(
        [_Resp(["a", "b"], "c1"), _Resp(["c"], "c2"), _Resp(["d"], None)]
    )
    tools = await service._list_all_tools(session)
    assert tools == ["a", "b", "c", "d"]
    assert session.cursors_seen == [None, "c1", "c2"]


async def test_repeated_cursor_raises():
    # Server keeps handing back the same cursor -> would loop forever.
    session = _CursorSession(["same", "same", "same"])
    with pytest.raises(DomainError, match="repeated tools/list cursor"):
        await service._list_all_tools(session)


async def test_cyclic_cursor_raises():
    # A -> B -> A cycle.
    session = _CursorSession(["A", "B", "A", "B"])
    with pytest.raises(DomainError, match="repeated tools/list cursor"):
        await service._list_all_tools(session)


async def test_endless_unique_cursors_are_capped(monkeypatch):
    monkeypatch.setattr(service, "MAX_TOOL_LIST_PAGES", 3)
    # Always a brand-new cursor: repeat-detection can't catch it; the cap must.
    session = _CursorSession([f"c{i}" for i in range(10)])
    with pytest.raises(DomainError, match="exceeded 3 tools/list pages"):
        await service._list_all_tools(session)
    assert session.call_count == 3
