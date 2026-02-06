from typing import Any, Annotated
from pydantic import BaseModel, Discriminator, Tag


class TextMessagePart(BaseModel):
    type: str = "text"
    text: str


class ReasoningMessagePart(BaseModel):
    type: str = "reasoning"
    text: str


class ToolMessagePart(BaseModel):
    type: str
    toolCallId: str
    toolName: str | None = None
    state: str
    input: Any | None = None
    output: Any | None = None
    errorText: str | None = None
    approval: Any | None = None


class FileMessagePart(BaseModel):
    type: str = "file"
    filename: str | None = None
    mediaType: str | None = None
    url: str | None = None


def get_message_part_type(value: Any) -> str:
    """Custom discriminator that handles dynamic tool-* types."""
    if isinstance(value, dict):
        type_val = value.get("type", "")
    else:
        type_val = getattr(value, "type", "")
    
    if isinstance(type_val, str) and type_val.startswith("tool-"):
        return "tool"
    return type_val


MessagePart = Annotated[
    Annotated[TextMessagePart, Tag("text")]
    | Annotated[ReasoningMessagePart, Tag("reasoning")]
    | Annotated[ToolMessagePart, Tag("tool")]
    | Annotated[FileMessagePart, Tag("file")],
    Discriminator(get_message_part_type),
]


class Message(BaseModel):
    """AI SDK client message format"""
    id: str
    role: str
    parts: list[MessagePart]
    metadata: dict | None = None