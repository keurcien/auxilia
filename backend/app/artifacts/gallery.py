"""Run-bound image gallery tool: the model picks the images and their order,
the chat displays them.

Bytes are fetched on the backend with the run's own credentials (the open MCP
sessions) and stored as gallery artifacts of the thread. The browser reads them
through the thread's authorized artifact routes; the model only ever sees
metadata, never image data, URLs signed with a key, or the key itself.
"""

import asyncio
import base64
import binascii
import ipaddress
import json
import re
import socket
import warnings
from collections.abc import Mapping
from datetime import datetime
from io import BytesIO
from typing import Annotated, Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastmcp.client import Client
from langchain_core.tools import InjectedToolCallId, tool
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from app.artifacts.service import ArtifactService
from app.artifacts.settings import artifact_settings
from app.database import AsyncSessionLocal
from app.threads.models import ThreadSource
from app.version import BACKEND_VERSION


MAX_IMAGES = 20
PREVIEW_EDGE = 2048
FETCH_TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 3
CONCURRENT_FETCHES = 4
# Some image hosts (e.g. Wikimedia) refuse anonymous library user agents.
USER_AGENT = f"Auxilia/{BACKEND_VERSION} (image gallery)"
# Pillow decoders limited to common photo formats.
DECODABLE_FORMATS = ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF")
# Side channels relay plain messages and files, not a browsable gallery.
CHANNELS_WITHOUT_GALLERY = {
    ThreadSource.slack: "Slack",
    ThreadSource.telegram: "Telegram",
    ThreadSource.whatsapp: "WhatsApp",
}


class GalleryImage(BaseModel):
    resource_uri: str | None = Field(
        default=None,
        max_length=2048,
        description="MCP resource URI of the image, as returned by a tool of a "
        "connected MCP server (e.g. a photo library's thumbnail resource).",
    )
    server: str | None = Field(
        default=None,
        max_length=200,
        description="Name of the MCP server whose tool returned resource_uri.",
    )
    url: str | None = Field(
        default=None, max_length=2048, description="A public https:// image URL."
    )
    caption: str | None = Field(default=None, max_length=300)
    taken_at: str | None = Field(
        default=None,
        max_length=64,
        description="When the photo was taken, ISO 8601, if the source gives it.",
    )
    location: str | None = Field(
        default=None,
        max_length=200,
        description="Where the photo was taken (place name), when known and relevant.",
    )

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.url) == bool(self.resource_uri):
            raise ValueError("Give each image either url or resource_uri")
        if self.resource_uri and not self.server:
            raise ValueError("resource_uri needs the server that returned it")
        return self


class ImageUnavailableError(Exception):
    """One image could not be shown. The message is safe to give the model."""


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_client(clients: Mapping[str, Client], name: str) -> Client:
    """The open session of the server the model named. Tool names expose a
    sanitized server name, so `photos_test` also finds "Photos test"."""
    if name in clients:
        return clients[name]
    for server, client in clients.items():
        if _name_key(server) == _name_key(name):
            return client
    raise ImageUnavailableError(f"no connected MCP server is named {name!r}")


async def read_mcp_image(client: Client, uri: str) -> bytes:
    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            result = await client.read_resource_mcp(uri)
    except TimeoutError as exc:
        raise ImageUnavailableError("the MCP server did not answer in time") from exc
    except Exception as exc:
        detail = str(exc)[:200] or type(exc).__name__
        raise ImageUnavailableError(
            f"the MCP server could not read it ({detail})"
        ) from exc
    limit = artifact_settings.max_bytes
    for item in result.contents:
        blob = getattr(item, "blob", None)
        if not isinstance(blob, str):
            continue
        if len(blob) * 3 // 4 > limit:
            raise ImageUnavailableError("the image is larger than the size limit")
        try:
            return base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageUnavailableError("the MCP server returned invalid data") from exc
    raise ImageUnavailableError("the resource is not an image")


async def public_address(host: str, port: int) -> str:
    """Resolve `host` and require every address to be public, so a model-chosen
    URL can never reach the backend's own network."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ImageUnavailableError(f"the host {host} could not be resolved") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address | None] = []
    for *_, sockaddr in infos:
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            addresses.append(None)
    if not addresses or any(a is None or not a.is_global for a in addresses):
        raise ImageUnavailableError("the URL does not point to a public address")
    return str(addresses[0])


async def fetch_url_image(url: str) -> bytes:
    limit = artifact_settings.max_bytes
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ImageUnavailableError("only https:// image URLs can be shown")
        if parsed.username or parsed.password:
            raise ImageUnavailableError("URLs with credentials are not accepted")
        port = parsed.port or 443
        address = await public_address(parsed.hostname, port)
        # Connect to the vetted address; TLS still verifies the hostname (SNI).
        literal = f"[{address}]" if ":" in address else address
        pinned = urlunsplit(
            ("https", f"{literal}:{port}", parsed.path or "/", parsed.query, "")
        )
        host = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
        try:
            async with (
                httpx.AsyncClient(
                    timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False
                ) as client,
                client.stream(
                    "GET",
                    pinned,
                    headers={
                        "Host": host,
                        "Accept": "image/*",
                        "User-Agent": USER_AGENT,
                    },
                    extensions={"sni_hostname": parsed.hostname},
                ) as response,
            ):
                if response.is_redirect and response.headers.get("location"):
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise ImageUnavailableError(
                        f"the image server answered HTTP {response.status_code}"
                    )
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > limit:
                        raise ImageUnavailableError(
                            "the image is larger than the size limit"
                        )
                return bytes(data)
        except httpx.HTTPError as exc:
            raise ImageUnavailableError(
                f"the image could not be downloaded ({type(exc).__name__})"
            ) from exc
    raise ImageUnavailableError("the image URL redirects too many times")


def exif_taken_at(image: Image.Image) -> datetime | None:
    exif = image.getexif()
    raw = exif.get_ifd(ExifTags.IFD.Exif).get(
        ExifTags.Base.DateTimeOriginal
    ) or exif.get(ExifTags.Base.DateTime)
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def make_preview(data: bytes) -> tuple[bytes, int, int, datetime | None]:
    """Decode, orient and downscale to a WebP preview. Metadata (EXIF, GPS) is
    not carried over: the stored image holds pixels only."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(data), formats=DECODABLE_FORMATS) as source:
                source.load()
                taken_at = exif_taken_at(source)
                image = ImageOps.exif_transpose(source)
            image.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
            if image.mode not in ("RGB", "RGBA"):
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
            out = BytesIO()
            image.save(out, "WEBP", quality=85)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageUnavailableError("the image is too large to display") from exc
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise ImageUnavailableError(
                "the file is not an image format the chat can display"
            ) from exc
    return out.getvalue(), image.width, image.height, taken_at


def parse_taken_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def show_images_tool(
    *,
    workspace_id: UUID,
    thread_id: str,
    source: ThreadSource,
    clients: Mapping[str, Client],
):
    @tool(response_format="content_and_artifact")
    async def show_images(
        images: list[GalleryImage],
        tool_call_id: Annotated[str, InjectedToolCallId],
        title: str | None = None,
    ):
        """Show images in the chat as a gallery the user can browse (arrows,
        swipe, keyboard, click to enlarge). Use it whenever the user asks to see
        photos or images, after finding them with another tool.

        Pass the images in the order they should appear, e.g. newest first for
        "my last 5 photos". A single image is shown on its own.
        Each image needs exactly one source:
        - resource_uri + server: an MCP resource URI returned by a connected
          server's tool, and that server's name. Preferred for private
          libraries: the server's credentials stay on the backend.
        - url: a public https:// image URL.
        Add taken_at (ISO 8601) and location when the source tool gives them;
        they appear as a discreet caption. Never pass image data.

        The result says which images are displayed and which failed. Only
        describe displayed images as shown, and tell the user about failures.
        """
        if not 1 <= len(images) <= MAX_IMAGES:
            raise ValueError(f"Show between 1 and {MAX_IMAGES} images at a time")
        channel = CHANNELS_WITHOUT_GALLERY.get(source)
        if channel is not None:
            return json.dumps(
                {
                    "displayed": 0,
                    "note": f"This conversation takes place in {channel}, which "
                    "cannot display image galleries. No image was shown. Tell "
                    "the user, and describe the results in text instead.",
                }
            ), None

        semaphore = asyncio.Semaphore(CONCURRENT_FETCHES)

        async def prepare(image: GalleryImage):
            async with semaphore:
                if image.resource_uri:
                    client = find_client(clients, image.server or "")
                    data = await read_mcp_image(client, image.resource_uri)
                else:
                    data = await fetch_url_image(image.url or "")
            return await asyncio.to_thread(make_preview, data)

        outcomes = await asyncio.gather(
            *(prepare(image) for image in images), return_exceptions=True
        )
        failed: list[dict[str, Any]] = []
        ready = []
        for position, (image, outcome) in enumerate(
            zip(images, outcomes, strict=True), start=1
        ):
            if isinstance(outcome, ImageUnavailableError):
                failed.append({"position": position, "reason": str(outcome)})
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                ready.append((position, image, outcome))

        shown: list[dict[str, Any]] = []
        if ready:
            # Committed before the tool result is emitted, so the gallery's
            # images resolve as soon as it renders.
            async with AsyncSessionLocal() as db:
                service = ArtifactService(db, workspace_id)
                try:
                    for position, image, (data, width, height, exif_time) in ready:
                        taken_at = parse_taken_at(image.taken_at) or exif_time
                        label = image.caption or image.location or f"Image {position}"
                        row = await service.publish_gallery_image(
                            thread_id=thread_id,
                            tool_call_id=tool_call_id,
                            position=position,
                            title=label,
                            filename=f"image-{position}.webp",
                            mime_type="image/webp",
                            data=data,
                        )
                        shown.append(
                            {
                                "id": str(row.id),
                                "position": position,
                                "width": width,
                                "height": height,
                                "caption": image.caption,
                                "taken_at": taken_at.isoformat() if taken_at else None,
                                "location": image.location,
                            }
                        )
                except BaseException:
                    await service.discard_uploads()
                    raise
                await db.commit()

        summary: dict[str, Any] = {
            "displayed": len(shown),
            "images": [
                {
                    key: item[key]
                    for key in ("position", "taken_at", "location", "caption")
                    if item[key] is not None
                }
                for item in shown
            ],
        }
        if failed:
            summary["failed"] = failed
        summary["note"] = (
            "The user now sees these images in a gallery under this tool call. "
            "Do not repeat them as links or markdown images."
            if shown
            else "No image could be displayed. Tell the user why; do not say "
            "that an image was shown."
        )
        artifact = (
            {
                "image_gallery": {
                    "title": title,
                    "images": [
                        {key: value for key, value in item.items() if key != "position"}
                        for item in shown
                    ],
                }
            }
            if shown
            else None
        )
        # Tool-result content must be a string for every provider adapter.
        return json.dumps(summary), artifact

    return show_images
