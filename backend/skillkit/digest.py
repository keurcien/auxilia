"""Per-skill content digest.

``sha256`` over the sorted files: NFC path, a NUL, the 8-byte big-endian
length, the bytes. Paths are POSIX and relative to the skill directory.
Modes and mtimes are not part of it, so two checkouts of the same commit on
different filesystems digest the same. Symlinks never reach it (rejected
before).
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping


PREFIX = "sha256:"


def normalize_path(path: str) -> str:
    return unicodedata.normalize("NFC", path.replace("\\", "/")).strip("/")


def bundle_digest(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(normalize_path(p) for p in files):
        content = files[path] if path in files else _lookup(files, path)
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return PREFIX + digest.hexdigest()


def set_digest(digests: Iterable[str]) -> str:
    """One digest for a *set* of skills: the digest of the sorted per-skill
    digests. What a sandbox upload marker records."""
    digest = hashlib.sha256()
    for item in sorted(digests):
        digest.update(item.encode("ascii"))
        digest.update(b"\n")
    return PREFIX + digest.hexdigest()


def _lookup(files: Mapping[str, bytes], normalized: str) -> bytes:
    for path, content in files.items():
        if normalize_path(path) == normalized:
            return content
    raise KeyError(normalized)
