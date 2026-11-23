"""Validation and normalization for user-uploaded resource images."""

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from statistics import median
from typing import cast

from fastapi import Response, UploadFile
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from app.exceptions import DomainValidationError


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000
OUTPUT_SIZE = (512, 512)
OUTPUT_MEDIA_TYPE = "image/webp"
NOTIFICATION_BADGE_SIZE = (96, 96)
NOTIFICATION_BADGE_MEDIA_TYPE = "image/png"


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


async def process_notification_badge(upload: UploadFile) -> ProcessedImage:
    """Produce Android's white-on-transparent monochrome notification badge."""
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DomainValidationError("Image must be 5 MB or smaller")
    if not raw:
        raise DomainValidationError("Image file is empty")
    return await asyncio.to_thread(_process_notification_badge, raw)


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
                "transparency" in normalized.info
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
    except Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError:
        raise DomainValidationError("Invalid or corrupted image") from None

    data = output.getvalue()
    return ProcessedImage(
        data=data,
        media_type=OUTPUT_MEDIA_TYPE,
        sha256=sha256(data).hexdigest(),
    )


def _process_notification_badge(raw: bytes) -> ProcessedImage:
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
                "transparency" in normalized.info
            )
            normalized = normalized.convert("RGBA")
            alpha = normalized.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            if alpha_max == 0:
                raise DomainValidationError(
                    "Notification badge must contain a visible icon"
                )
            if not has_alpha or alpha_min == 255:
                rgb = normalized.convert("RGB")
                width, height = rgb.size
                samples = tuple(
                    cast(tuple[int, int, int], rgb.getpixel(coordinates))
                    for coordinates in (
                        (0, 0),
                        (width - 1, 0),
                        (0, height - 1),
                        (width - 1, height - 1),
                    )
                )
                background = tuple(
                    int(median(sample[channel] for sample in samples))
                    for channel in range(3)
                )
                difference = ImageChops.difference(
                    rgb,
                    Image.new("RGB", rgb.size, background),
                )
                red, green, blue = difference.split()
                alpha = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                alpha = alpha.point(lambda value: min(255, max(0, (value - 8) * 3)))
                if alpha.getextrema()[1] == 0:
                    raise DomainValidationError(
                        "Notification badge must contain a visible icon"
                    )
            bounds = alpha.getbbox()
            if bounds is None:
                raise DomainValidationError(
                    "Notification badge must contain a visible icon"
                )

            content = ImageOps.contain(
                alpha,
                NOTIFICATION_BADGE_SIZE,
                method=Image.Resampling.LANCZOS,
            )
            badge_alpha = Image.new("L", NOTIFICATION_BADGE_SIZE, 0)
            offset = (
                (NOTIFICATION_BADGE_SIZE[0] - content.width) // 2,
                (NOTIFICATION_BADGE_SIZE[1] - content.height) // 2,
            )
            badge_alpha.paste(content, offset)
            badge = Image.new("RGBA", NOTIFICATION_BADGE_SIZE, (255, 255, 255, 0))
            badge.putalpha(badge_alpha)

            output = BytesIO()
            badge.save(output, format="PNG", optimize=True)
    except DomainValidationError:
        raise
    except Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError:
        raise DomainValidationError("Invalid or corrupted image") from None

    data = output.getvalue()
    return ProcessedImage(
        data=data,
        media_type=NOTIFICATION_BADGE_MEDIA_TYPE,
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
    if if_none_match:
        candidates = {candidate.strip() for candidate in if_none_match.split(",")}
        normalized_candidates = {
            candidate[2:] if candidate.startswith("W/") else candidate
            for candidate in candidates
        }
        if "*" in candidates or etag in normalized_candidates:
            return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)
