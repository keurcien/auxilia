"""Manages the lifecycle of text and reasoning content streams."""

import uuid
from collections.abc import AsyncGenerator

from .sse import format_sse_event


class ContentStreamManager:
    """
    Tracks whether text and reasoning streams are open, and handles
    the start/delta/end transitions between them.

    Text and reasoning are mutually exclusive — opening one closes the other.
    """

    def __init__(self):
        self.text_id: str = str(uuid.uuid4())
        self.reasoning_id: str = str(uuid.uuid4())
        self._text_open: bool = False
        self._reasoning_open: bool = False

    @property
    def has_open_stream(self) -> bool:
        return self._text_open or self._reasoning_open

    async def emit_text(self, text: str) -> AsyncGenerator[str, None]:
        """Emit a text delta, opening the text stream if needed."""
        if not text:
            return

        if self._reasoning_open:
            yield format_sse_event("reasoning-end", id=self.reasoning_id)
            self._reasoning_open = False

        if not self._text_open:
            yield format_sse_event("text-start", id=self.text_id)
            self._text_open = True

        yield format_sse_event("text-delta", id=self.text_id, delta=text)

    async def emit_reasoning(self, thinking: str) -> AsyncGenerator[str, None]:
        """Emit a reasoning delta, opening the reasoning stream if needed."""
        if not thinking:
            return

        if self._text_open:
            yield format_sse_event("text-end", id=self.text_id)
            self._text_open = False

        if not self._reasoning_open:
            yield format_sse_event("reasoning-start", id=self.reasoning_id)
            self._reasoning_open = True

        yield format_sse_event("reasoning-delta", id=self.reasoning_id, delta=thinking)

    async def emit_content_array(self, content_list: list) -> AsyncGenerator[str, None]:
        """Route a mixed content array (text + thinking blocks) to the right stream."""
        for item in content_list:
            if not isinstance(item, dict):
                continue
            content_type = item.get("type")
            if content_type == "text":
                async for event in self.emit_text(item.get("text", "")):
                    yield event
            elif content_type == "thinking":
                async for event in self.emit_reasoning(item.get("thinking", "")):
                    yield event

    async def close_all(self) -> AsyncGenerator[str, None]:
        """Close any open content streams."""
        if self._reasoning_open:
            yield format_sse_event("reasoning-end", id=self.reasoning_id)
            self._reasoning_open = False

        if self._text_open:
            yield format_sse_event("text-end", id=self.text_id)
            self._text_open = False
