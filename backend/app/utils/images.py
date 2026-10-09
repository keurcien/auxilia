"""Validation and normalization for user-uploaded resource images."""

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from fastapi import Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.exceptions import DomainValidationError


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000
OUTPUT_SIZE = (512, 512)
OUTPUT_MEDIA_TYPE = "image/webp"


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    media_type: str
    sha256: str


async def process_uploaded_image(upload: UploadFile) -> ProcessedImage:
    """Read a bounded upload and produce a metadata-free square WebP."""
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DomainValidationError("Image must be 5 MB or smaller")
    if not raw:
        raise DomainValidationError("Image file is empty")
    return await asyncio.to_thread(_process_image, raw)


def _process_image(raw: bytes) -> ProcessedImage:
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise DomainValidationError("Image must be JPEG, PNG, or WebP")
            if getattr(source, "n_frames", 1) != 1:
                raise DomainValidationError("Animated images are not supported")
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise DomainValidationError("Image dimensions are too large")

            source.load()
            normalized = ImageOps.exif_transpose(source)
            has_alpha = normalized.mode in {"RGBA", "LA"} or (
                normalized.mode == "P" and "transparency" in normalized.info
            )
            normalized = normalized.convert("RGBA" if has_alpha else "RGB")
            normalized = ImageOps.fit(
                normalized,
                OUTPUT_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )

            output = BytesIO()
            normalized.save(output, format="WEBP", quality=85, method=6)
    except DomainValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise DomainValidationError("Invalid or corrupted image") from None

    data = output.getvalue()
    return ProcessedImage(
        data=data,
        media_type=OUTPUT_MEDIA_TYPE,
        sha256=sha256(data).hexdigest(),
    )


def image_response(
    *,
    data: bytes,
    media_type: str,
    digest: str,
    if_none_match: str | None,
) -> Response:
    etag = f'"{digest}"'
    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if if_none_match and etag in {
        candidate.strip() for candidate in if_none_match.split(",")
    }:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)
