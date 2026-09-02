"""DeepSeek content-block translator — surfaces `reasoning_content` as a
standard `reasoning` block.

`ChatDeepSeek` stamps `model_provider="deepseek"` on its messages and keeps
the model's chain of thought in `additional_kwargs["reasoning_content"]`
(a Chat Completions extension). langchain-core registers no translator for
"deepseek", so `AIMessage.content_blocks` falls back to best-effort parsing
and never sees that field — and the v3 streaming bridge
(`_compat_bridge.chunks_to_events`) builds the wire grammar from
`content_blocks`, so DeepSeek reasoning would silently vanish from the
protocol stream (and from the persisted message content, which under v3 is
the assembled block list).

Registering this translator makes each chunk's reasoning a `reasoning`
block ahead of the Chat Completions blocks (text / tool-call chunks), so the
stream carries `reasoning-delta`s and the assembled message keeps a
`reasoning` block that history rendering already understands. Round-trips
are unaffected: `_convert_from_v1_to_chat_completions` drops `reasoning`
blocks before a message is sent back to the API.
"""

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.block_translators import register_translator
from langchain_core.messages.block_translators.openai import (
    _convert_to_v1_from_chat_completions,
    _convert_to_v1_from_chat_completions_chunk,
)


_REASONING_KEY = "reasoning_content"


def _reasoning_block(message: AIMessage) -> list[dict[str, Any]]:
    reasoning = (message.additional_kwargs or {}).get(_REASONING_KEY)
    if not isinstance(reasoning, str) or not reasoning:
        return []
    return [{"type": "reasoning", "reasoning": reasoning}]


def translate_content(message: AIMessage) -> list[Any]:
    return [*_reasoning_block(message), *_convert_to_v1_from_chat_completions(message)]


def translate_content_chunk(chunk: AIMessageChunk) -> list[Any]:
    return [
        *_reasoning_block(chunk),
        *_convert_to_v1_from_chat_completions_chunk(chunk),
    ]


def register_deepseek_translator() -> None:
    """Idempotent; called at import of the model catalog."""
    register_translator("deepseek", translate_content, translate_content_chunk)
