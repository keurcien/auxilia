"""Server-Sent Events (SSE) formatter for AI SDK v5 streaming protocol."""

import json
from typing import Any


def format_sse_event(event_type: str, **data: Any) -> str:
    """Format a single event as an SSE data line."""
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload)}\n\n"


SSE_DONE = "data: [DONE]\n\n"
