"""DeepSeek `reasoning_content` must reach `content_blocks`, which is what the
v3 streaming bridge serializes onto the wire."""

from langchain_core.messages import AIMessage, AIMessageChunk

import app.model_providers.catalog  # noqa: F401 — registers the translator


def test_chunk_reasoning_content_becomes_a_reasoning_block():
    chunk = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning_content": "hmm"},
        response_metadata={"model_provider": "deepseek"},
    )
    assert chunk.content_blocks == [{"type": "reasoning", "reasoning": "hmm"}]


def test_chunk_text_and_tool_call_chunks_keep_the_chat_completions_shape():
    chunk = AIMessageChunk(
        content="Hel",
        tool_call_chunks=[{"id": "c1", "name": "f", "args": "{", "index": 0}],
        response_metadata={"model_provider": "deepseek"},
    )
    blocks = chunk.content_blocks
    assert blocks[0] == {"type": "text", "text": "Hel"}
    assert blocks[1]["type"] == "tool_call_chunk"
    assert blocks[1]["id"] == "c1"


def test_whole_message_reasoning_precedes_text():
    msg = AIMessage(
        content="answer",
        additional_kwargs={"reasoning_content": "because"},
        response_metadata={"model_provider": "deepseek"},
    )
    assert msg.content_blocks == [
        {"type": "reasoning", "reasoning": "because"},
        {"type": "text", "text": "answer"},
    ]
