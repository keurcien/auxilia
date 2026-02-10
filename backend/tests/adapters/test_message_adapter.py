from langchain_core.messages import HumanMessage

from app.adapters.message_adapter import to_langchain_message
from app.models.message import Message, TextMessagePart


def test_to_langchain_message():
    message = Message(id="1", role="user", parts=[
                      TextMessagePart(text="Lorem ipsum")])
    langchain_message = to_langchain_message(message)
    assert langchain_message.content[0]["text"] == "Lorem ipsum"
    assert isinstance(langchain_message, HumanMessage)
