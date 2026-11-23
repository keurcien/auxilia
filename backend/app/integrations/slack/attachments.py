import base64
import mimetypes
from dataclasses import dataclass
from typing import Any

import httpx
from slack_sdk.web.async_client import AsyncWebClient

from app.integrations.slack.models import SlackFile


MAX_SLACK_FILES = 10
MAX_SLACK_FILE_BYTES = 50 * 1024 * 1024
MAX_SLACK_FILES_TOTAL_BYTES = 100 * 1024 * 1024
_GENERIC_BINARY_MIME_TYPES = frozenset(
    {"", "application/octet-stream", "binary/octet-stream"}
)
_IMAGE_MIME_TYPES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})
_TEXT_APPLICATION_MIME_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/toml",
        "application/x-httpd-php",
        "application/x-sh",
        "application/xml",
        "application/yaml",
        "message/rfc822",
    }
)


@dataclass(frozen=True)
class SlackAttachments:
    content_blocks: list[dict[str, Any]]
    rejected_names: list[str]


def _filename(file: SlackFile) -> str:
    name = (file.name or file.title or "").strip()
    return name or f"Slack file {file.id}"


def _declared_mime(file: SlackFile) -> str | None:
    declared = (file.mimetype or "").split(";", 1)[0].strip().lower()
    if declared not in _GENERIC_BINARY_MIME_TYPES and "/" in declared:
        return declared
    guessed, _ = mimetypes.guess_type(_filename(file))
    if guessed and guessed.lower() not in _GENERIC_BINARY_MIME_TYPES:
        return guessed.lower()
    return None


async def _download(
    client: httpx.AsyncClient,
    file: SlackFile,
    token: str,
    max_bytes: int,
) -> bytes | None:
    url = file.url_private_download or file.url_private
    if not url or max_bytes <= 0 or (file.size is not None and file.size > max_bytes):
        return None
    async with client.stream(
        "GET",
        url,
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            return None
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                return None
            chunks.append(chunk)
    return b"".join(chunks)


def _content_block(file: SlackFile, data: bytes) -> dict[str, Any] | None:
    mime_type = _declared_mime(file)
    if mime_type is None:
        if data.startswith(b"%PDF-"):
            mime_type = "application/pdf"
        elif data.startswith((b"GIF87a", b"GIF89a")):
            mime_type = "image/gif"
        elif data.startswith(b"\xff\xd8\xff"):
            mime_type = "image/jpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime_type = "image/png"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            mime_type = "image/webp"
    is_text = mime_type is None or mime_type.startswith("text/")
    is_text = is_text or mime_type in _TEXT_APPLICATION_MIME_TYPES
    if is_text:
        if b"\x00" in data:
            return None
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        control_chars = sum(
            1 for char in text if ord(char) < 32 and char not in "\n\r\t\f\b"
        )
        if text and control_chars / len(text) > 0.01:
            return None
        return {
            "type": "text",
            "text": f'Attached file "{_filename(file)}":\n\n{text}',
        }
    if mime_type not in _IMAGE_MIME_TYPES and mime_type != "application/pdf":
        return None
    if mime_type == "application/pdf" and not data.startswith(b"%PDF-"):
        return None
    image_signatures = {
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if mime_type in _IMAGE_MIME_TYPES and not image_signatures[mime_type]:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    if mime_type in _IMAGE_MIME_TYPES:
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{encoded}",
                "detail": "auto",
            },
        }
    return {
        "type": "file",
        "mime_type": mime_type,
        "base64": encoded,
        "filename": _filename(file),
    }


async def load_slack_attachments(
    slack: AsyncWebClient,
    files: list[SlackFile],
) -> SlackAttachments:
    token = slack.token
    if not token:
        return SlackAttachments([], [_filename(file) for file in files])

    content_blocks: list[dict[str, Any]] = []
    rejected_names: list[str] = []
    total_size = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for file in files[:MAX_SLACK_FILES]:
            name = _filename(file)
            remaining = MAX_SLACK_FILES_TOTAL_BYTES - total_size
            try:
                data = await _download(
                    client,
                    file,
                    token,
                    min(MAX_SLACK_FILE_BYTES, remaining),
                )
            except httpx.HTTPError, ValueError:
                data = None
            if data is None:
                rejected_names.append(name)
                continue
            # Downloaded bytes consume the batch budget even if their format is
            # later rejected, so one message can never transfer more than the
            # advertised total.
            total_size += len(data)
            block = _content_block(file, data)
            if block is None:
                rejected_names.append(name)
                continue
            content_blocks.append(block)

    rejected_names.extend(_filename(file) for file in files[MAX_SLACK_FILES:])
    return SlackAttachments(content_blocks, rejected_names)
