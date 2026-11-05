import json
from unittest.mock import AsyncMock

import pytest

from app.integrations.slack.history import thread_history_messages


async def test_imports_all_pages_in_order_without_current_or_later_messages():
    client = AsyncMock()
    client.conversations_replies.side_effect = [
        {
            "messages": [{"ts": "1.0", "user": "U1", "text": "root"}],
            "response_metadata": {"next_cursor": "page2"},
        },
        {
            "messages": [
                {"ts": "2.0", "user": "U2", "text": "reply"},
                {"ts": "1.0", "user": "U1", "text": "root"},
                {"ts": "3.0", "bot_id": "B1", "text": "bot context"},
                {"ts": "4.0", "text": "current"},
                {"ts": "5.0", "text": "future"},
            ]
        },
    ]
    result = await thread_history_messages(client, "C1", "1.0", "4.0")
    assert len(result) == 1
    assert result[0]["type"] == "human"
    transcript = json.loads(result[0]["content"].split("\n", 1)[1])
    assert [m["text"] for m in transcript] == ["root", "reply", "bot context"]
    assert [m["author"] for m in transcript] == ["U1", "U2", "B1"]
    assert client.conversations_replies.call_args.kwargs["cursor"] == "page2"
    assert client.conversations_replies.call_args.kwargs["latest"] == "4.0"


async def test_empty_history():
    client = AsyncMock()
    client.conversations_replies.return_value = {"messages": []}
    assert await thread_history_messages(client, "C1", "1.0", "2.0") == []


async def test_incomplete_history_is_not_silently_accepted():
    client = AsyncMock()
    client.conversations_replies.return_value = {"messages": [], "has_more": True}
    with pytest.raises(ValueError, match="incomplete history"):
        await thread_history_messages(client, "C1", "1.0", "2.0")
