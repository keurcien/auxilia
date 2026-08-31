from langchain_ai_sdk_adapter import to_lc_messages
from langchain_core.messages import HumanMessage


async def test_to_lc_messages():
    messages = [
        {"id": "1", "role": "user", "parts": [{"type": "text", "text": "Lorem ipsum"}]}
    ]
    langchain_messages = await to_lc_messages(messages)
    assert len(langchain_messages) == 1
    assert isinstance(langchain_messages[0], HumanMessage)
    assert langchain_messages[0].content == "Lorem ipsum"
