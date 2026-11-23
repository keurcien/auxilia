from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.runtime.protocol.events import KNOWN_CHANNELS
from app.runtime.runs.models import RunDB
from app.runtime.runs.state import MultitaskStrategy, RunStatus


class RunCreate(BaseModel):
    """Client payload for `POST /threads/{thread_id}/runs`.

    `input` starts a new turn; `command` resumes a HITL interrupt. `config`
    mirrors the langgraph-sdk run config (carries `trigger` / overrides).
    """

    input: dict | None = None
    command: dict | None = None
    config: dict | None = None
    output_schema: dict | None = None
    multitask_strategy: MultitaskStrategy = "reject"


#: What a `/runs/stream` consumer gets unless it asks otherwise: the answer's
#: tokens, tool activity, the run's lifecycle and approval requests.
DEFAULT_STREAM_CHANNELS = ["messages", "tools", "lifecycle", "input"]


class RunStreamCreate(RunCreate):
    """Client payload for `POST /threads/{thread_id}/runs/stream`: the
    `/invoke` body plus what to relay.

    `channels` are Agent Streaming Protocol channels. `subagents` also relays
    events from inside subagents (namespaced), which are otherwise dropped.
    Approval requests (`input`) are the exception to both: they are always
    relayed, from every agent.
    """

    channels: list[str] = Field(default_factory=lambda: list(DEFAULT_STREAM_CHANNELS))
    subagents: bool = False

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, channels: list[str]) -> list[str]:
        """A misspelt channel would otherwise just deliver nothing."""
        unknown = [
            c
            for c in channels
            if c not in KNOWN_CHANNELS and not c.startswith("custom:")
        ]
        if unknown:
            raise ValueError(
                f"Unknown channels {unknown}; expected any of {sorted(KNOWN_CHANNELS)} "
                "or custom:<name>."
            )
        return channels


class RunResponse(BaseModel):
    """API projection of a run — operational state only (no input/command)."""

    id: str
    workspace_id: UUID
    thread_id: str
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    kind: Literal["prompt", "resume", "regenerate", "other"]
    input_message_id: str | None = None

    @classmethod
    def from_record(cls, record: RunDB) -> RunResponse:
        messages = (record.input or {}).get("messages")
        input_message = (
            messages[0]
            if isinstance(messages, list)
            and len(messages) == 1
            and isinstance(messages[0], dict)
            and messages[0].get("type") == "human"
            else None
        )
        kind: Literal["prompt", "resume", "regenerate", "other"]
        if record.trigger == "regenerate-message":
            kind = "regenerate"
        elif input_message is not None:
            kind = "prompt"
        elif record.command is not None:
            kind = "resume"
        else:
            kind = "other"
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            thread_id=record.thread_id,
            status=record.status,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            kind=kind,
            input_message_id=(
                str(input_message["id"])
                if input_message is not None and input_message.get("id")
                else None
            ),
        )


class InlineTextFile(BaseModel):
    block_index: int = Field(ge=0)
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=255)


class QueuedPromptCreate(BaseModel):
    content: str | list[dict[str, Any]] | None = None
    text: str | None = Field(default=None, min_length=1, max_length=100_000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)
    display_text: str | None = Field(default=None, max_length=100_000)
    inline_text_files: list[InlineTextFile] = Field(default_factory=list, max_length=10)


class QueuedPromptPatch(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class QueuedPromptOrder(BaseModel):
    ordered_ids: list[str]


class QueuedPromptAttachmentResponse(BaseModel):
    id: UUID | None = None
    filename: str
    media_type: str


class QueuedPromptResponse(BaseModel):
    id: str
    text: str
    attachments: list[QueuedPromptAttachmentResponse]
    position: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: RunDB) -> QueuedPromptResponse | None:
        messages = (record.input or {}).get("messages")
        if not isinstance(messages, list) or len(messages) != 1:
            return None
        message = messages[0]
        if not isinstance(message, dict) or message.get("type") != "human":
            return None
        content = message.get("content")
        if not isinstance(content, (str, list)) or record.queue_position is None:
            return None
        if isinstance(content, list) and not all(
            isinstance(block, dict) for block in content
        ):
            return None
        return cls(
            id=record.id,
            text=queued_prompt_text(message),
            attachments=queued_prompt_attachments(message),
            position=record.queue_position,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def _inline_text_files(message: dict[str, Any]) -> dict[int, dict[str, Any]]:
    additional_kwargs = message.get("additional_kwargs")
    items = (
        additional_kwargs.get("inline_text_files")
        if isinstance(additional_kwargs, dict)
        else None
    )
    if not isinstance(items, list):
        return {}
    return {
        item["block_index"]: item
        for item in items
        if isinstance(item, dict)
        and type(item.get("block_index")) is int
        and item["block_index"] >= 0
    }


def queued_prompt_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    inline_indexes = set(_inline_text_files(message))
    return "\n".join(
        block["text"]
        for index, block in enumerate(content)
        if block.get("type") == "text"
        and index not in inline_indexes
        and isinstance(block.get("text"), str)
    )


def queued_prompt_attachments(
    message: dict[str, Any],
) -> list[QueuedPromptAttachmentResponse]:
    content = message.get("content")
    if isinstance(content, str):
        content = []
    attachments: list[QueuedPromptAttachmentResponse] = []
    inline_by_index = _inline_text_files(message)
    for index, block in enumerate(content if isinstance(content, list) else []):
        if block.get("type") == "image_url":
            image = block.get("image_url")
            url = (
                image
                if isinstance(image, str)
                else image.get("url", "")
                if isinstance(image, dict)
                else ""
            )
            media_type = "image/jpeg"
            if isinstance(url, str) and url.startswith("data:"):
                declared_type = url[5:].split(";", 1)[0].split(",", 1)[0]
                if declared_type:
                    media_type = declared_type
            extension = media_type.split("/", 1)[-1].split("+", 1)[0]
            extension = extension.removeprefix("x-").replace("jpeg", "jpg")
            attachments.append(
                QueuedPromptAttachmentResponse(
                    filename=f"Image.{extension or 'jpg'}",
                    media_type=media_type,
                )
            )
        elif block.get("type") == "file":
            attachments.append(
                QueuedPromptAttachmentResponse(
                    filename=block.get("filename")
                    if isinstance(block.get("filename"), str)
                    else "file",
                    media_type=block.get("mime_type")
                    if isinstance(block.get("mime_type"), str)
                    else "application/octet-stream",
                )
            )
        elif block.get("type") == "text" and index in inline_by_index:
            inline_file = inline_by_index[index]
            attachments.append(
                QueuedPromptAttachmentResponse(
                    filename=(
                        inline_file["filename"]
                        if isinstance(inline_file.get("filename"), str)
                        else "file.txt"
                    ),
                    media_type=(
                        inline_file["media_type"]
                        if isinstance(inline_file.get("media_type"), str)
                        else "text/plain"
                    ),
                )
            )
    additional_kwargs = message.get("additional_kwargs")
    stored = (
        additional_kwargs.get("attachments")
        if isinstance(additional_kwargs, dict)
        else None
    )
    if isinstance(stored, list):
        stored_responses: list[QueuedPromptAttachmentResponse] = []
        for item in stored:
            if not isinstance(item, dict):
                continue
            try:
                attachment_id = UUID(str(item.get("id")))
            except TypeError, ValueError:
                continue
            stored_responses.append(
                QueuedPromptAttachmentResponse(
                    id=attachment_id,
                    filename=(
                        item["filename"]
                        if isinstance(item.get("filename"), str)
                        else "file"
                    ),
                    media_type=(
                        item["media_type"]
                        if isinstance(item.get("media_type"), str)
                        else "application/octet-stream"
                    ),
                )
            )
        for stored_item in stored_responses:
            duplicate = next(
                (
                    index
                    for index, inline_item in enumerate(attachments)
                    if inline_item.id is None
                    and (
                        (
                            stored_item.media_type.startswith("image/")
                            and inline_item.media_type.startswith("image/")
                        )
                        or (
                            inline_item.filename == stored_item.filename
                            and inline_item.media_type == stored_item.media_type
                        )
                    )
                ),
                None,
            )
            if duplicate is not None:
                attachments.pop(duplicate)
        attachments.extend(stored_responses)
    return attachments


def has_queued_prompt_content(
    content: str | list[dict[str, Any]],
) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not content:
        return False
    for block in content:
        if (
            block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"].strip()
        ):
            return True
        if block.get("type") == "image_url":
            image = block.get("image_url")
            if isinstance(image, str) and image:
                return True
            if (
                isinstance(image, dict)
                and isinstance(image.get("url"), str)
                and image["url"]
            ):
                return True
        if block.get("type") == "file" and isinstance(block.get("base64"), str):
            return True
    return False


def queued_prompt_content_error(
    content: str | list[dict[str, Any]],
    inline_text_files: list[InlineTextFile],
) -> str | None:
    if isinstance(content, str):
        if inline_text_files:
            return "Inline text files require message content blocks"
        return (
            "A prompt can contain at most 100,000 characters"
            if len(content) > 100_000
            else None
        )
    if not all(isinstance(block, dict) for block in content):
        return "Message content blocks must be objects"
    indexes = [inline_file.block_index for inline_file in inline_text_files]
    if len(indexes) != len(set(indexes)):
        return "Inline text file references must be unique"
    inline_by_index = {
        inline_file.block_index: inline_file for inline_file in inline_text_files
    }
    if any(
        index >= len(content)
        or content[index].get("type") != "text"
        or not isinstance(content[index].get("text"), str)
        for index in inline_by_index
    ):
        return "An inline text file references an invalid content block"
    prompt_text_length = sum(
        len(block["text"])
        for index, block in enumerate(content)
        if index not in inline_by_index
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )
    inline_text_length = 0
    for index, inline_file in inline_by_index.items():
        text = content[index]["text"]
        prefix = f'Attached text file "{inline_file.filename}":\n\n'
        inline_text_length += len(text.removeprefix(prefix))
    if prompt_text_length > 100_000:
        return "A prompt can contain at most 100,000 characters"
    if inline_text_length > 100_000:
        return "Text attachments can contain at most 100,000 characters per message"
    return None


def _content_file_media_types(content: str | list[dict[str, Any]]) -> list[str]:
    if isinstance(content, str):
        return []
    media_types: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "file":
            media_type = block.get("mime_type")
            media_types.append(
                media_type
                if isinstance(media_type, str)
                else "application/octet-stream"
            )
            continue
        if block.get("type") != "image_url":
            continue
        image = block.get("image_url")
        url = image if isinstance(image, str) else None
        if isinstance(image, dict):
            url = image.get("url")
        media_type = "image/jpeg"
        if isinstance(url, str) and url.startswith("data:"):
            declared = url[5:].split(";", 1)[0].split(",", 1)[0]
            if declared:
                media_type = declared
        media_types.append(media_type)
    return media_types


def run_input_content_error(agent_input: dict[str, Any]) -> str | None:
    messages = agent_input.get("messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "human":
            continue
        content = message.get("content")
        if not isinstance(content, (str, list)):
            continue
        kwargs = message.get("additional_kwargs")
        kwargs = kwargs if isinstance(kwargs, dict) else {}
        raw_inline = kwargs.get("inline_text_files", [])
        if not isinstance(raw_inline, list):
            return "Inline text file references must be a list"
        try:
            inline_text_files = [
                InlineTextFile.model_validate(item) for item in raw_inline
            ]
        except ValidationError:
            return "Inline text file metadata is invalid"
        if len(inline_text_files) > 10:
            return "A message can contain at most 10 files"
        error = queued_prompt_content_error(content, inline_text_files)
        if error is not None:
            return error
        raw_attachments = kwargs.get("attachments", [])
        if not isinstance(raw_attachments, list):
            return "Attachment references must be a list"
        unmatched_content = _content_file_media_types(content)
        for attachment in raw_attachments:
            media_type = (
                attachment.get("media_type") if isinstance(attachment, dict) else None
            )
            if not isinstance(media_type, str):
                continue
            try:
                unmatched_content.remove(media_type)
            except ValueError:
                continue
        file_count = (
            len(inline_text_files) + len(raw_attachments) + len(unmatched_content)
        )
        if file_count > 10:
            return "A message can contain at most 10 files"
        display_text = kwargs.get("display_text")
        if isinstance(display_text, str) and len(display_text) > 100_000:
            return "A prompt can contain at most 100,000 characters"
    return None


def queued_prompt_input(
    content: str | list[dict[str, Any]],
    attachments: list[dict[str, str]] | None = None,
    *,
    display_text: str | None = None,
    inline_text_files: list[InlineTextFile] | None = None,
) -> dict:
    message: dict[str, Any] = {"type": "human", "content": content}
    additional_kwargs = {
        **({"attachments": attachments} if attachments else {}),
        **({"display_text": display_text} if display_text is not None else {}),
        **(
            {
                "inline_text_files": [
                    inline_file.model_dump() for inline_file in inline_text_files
                ]
            }
            if inline_text_files
            else {}
        ),
    }
    if additional_kwargs:
        message["additional_kwargs"] = additional_kwargs
    return {"messages": [message]}


def queued_prompt_input_with_text(record: RunDB, text: str) -> dict:
    messages = (record.input or {}).get("messages")
    message = messages[0] if isinstance(messages, list) and len(messages) == 1 else {}
    content = message.get("content") if isinstance(message, dict) else None
    additional_kwargs = (
        message.get("additional_kwargs") if isinstance(message, dict) else None
    )
    if isinstance(additional_kwargs, dict):
        additional_kwargs = dict(additional_kwargs)
        if "display_text" in additional_kwargs:
            additional_kwargs["display_text"] = text
    if not isinstance(content, list):
        updated = queued_prompt_input(text)
        if isinstance(additional_kwargs, dict):
            additional_kwargs.pop("inline_text_files", None)
            updated["messages"][0]["additional_kwargs"] = additional_kwargs
        if isinstance(message, dict) and message.get("id"):
            updated["messages"][0]["id"] = message["id"]
        return updated
    inline_by_index = _inline_text_files(message)
    attachments: list[dict[str, Any]] = []
    updated_inline_files: list[dict[str, Any]] = []
    for index, block in enumerate(content):
        if not isinstance(block, dict) or (
            block.get("type") == "text" and index not in inline_by_index
        ):
            continue
        attachments.append(block)
        if index in inline_by_index:
            updated_inline_files.append(
                {
                    **inline_by_index[index],
                    "block_index": len(attachments),
                }
            )
    if isinstance(additional_kwargs, dict):
        additional_kwargs.pop("inline_text_files", None)
        if updated_inline_files:
            additional_kwargs["inline_text_files"] = updated_inline_files
    updated = queued_prompt_input([{"type": "text", "text": text}, *attachments])
    if isinstance(additional_kwargs, dict):
        updated["messages"][0]["additional_kwargs"] = additional_kwargs
    if isinstance(message, dict) and message.get("id"):
        updated["messages"][0]["id"] = message["id"]
    return updated
