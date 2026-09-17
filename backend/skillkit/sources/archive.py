"""Zip and tar archives, extracted in memory within bounds.

Zip-slip, absolute entries and symlinks are rejected. A single top-level
directory (what GitHub and GitLab tarballs have) is stripped so the tree
starts at the repository root.
"""

from __future__ import annotations

import io
import stat
import tarfile
import zipfile

from skillkit.digest import set_digest
from skillkit.errors import LimitExceeded, ValidationError
from skillkit.model import Limits, ResolvedSource
from skillkit.sources.base import resolve_tree


class ArchiveSource:
    def __init__(
        self,
        data: bytes,
        *,
        filename: str = "archive.zip",
        url: str | None = None,
        ref: str | None = None,
        revision: str | None = None,
        kind: str = "archive",
        subpath: str | None = None,
        full_depth: bool = False,
        limits: Limits = Limits(),
        strip_root: bool = True,
        enforce_directory_name: bool = True,
    ) -> None:
        self.data = data
        self.filename = filename
        self.url = url or filename
        self.ref = ref
        self.revision = revision
        self.kind = kind
        self.subpath = subpath
        self.full_depth = full_depth
        self.limits = limits
        self.strip_root = strip_root
        self.enforce_directory_name = enforce_directory_name

    def resolve(self) -> ResolvedSource:
        tree = extract(
            self.data, self.filename, self.limits, strip_root=self.strip_root
        )
        return resolve_tree(
            tree,
            kind=self.kind,
            url=self.url,
            ref=self.ref,
            revision=self.revision or "archive:" + set_digest(tree),
            subpath=self.subpath,
            full_depth=self.full_depth,
            limits=self.limits,
            enforce_directory_name=self.enforce_directory_name,
        )


def extract(
    data: bytes, filename: str, limits: Limits, *, strip_root: bool = True
) -> dict[str, bytes]:
    if len(data) > limits.max_download_bytes:
        raise LimitExceeded(
            f"archive is {len(data)} bytes; the limit is {limits.max_download_bytes}"
        )
    # Sniff the bytes first — hosts serve tarballs under arbitrary names —
    # and fall back to the filename for anything without a magic number.
    if data[:2] == b"\x1f\x8b" or data[257:262] == b"ustar":
        entries = _tar_entries(data, limits)
    elif data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        entries = _zip_entries(data, limits)
    elif filename.lower().endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        entries = _tar_entries(data, limits)
    else:
        try:
            entries = _zip_entries(data, limits)
        except zipfile.BadZipFile as exc:
            raise ValidationError("not a zip or tar archive", "E001") from exc
    return _strip_root(entries) if strip_root else entries


def _check_path(path: str) -> str:
    clean = path.replace("\\", "/")
    parts = clean.split("/")
    if (
        clean.startswith("/")
        or any(p in ("..", "") for p in parts[:-1])
        or ":" in parts[0]
        or clean.endswith("/..")
    ):
        raise ValidationError(f"unsafe archive path '{path}'", "E005")
    return "/".join(p for p in parts if p != ".")


def _zip_entries(data: bytes, limits: Limits) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > limits.max_files:
            raise LimitExceeded(
                f"archive holds {len(infos)} files; the limit is {limits.max_files}"
            )
        if sum(i.file_size for i in infos) > limits.max_extracted_bytes:
            raise LimitExceeded(
                f"archive unpacks to more than {limits.max_extracted_bytes} bytes"
            )
        entries: dict[str, bytes] = {}
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValidationError(f"symlink in archive: {info.filename}", "E006")
            path = _check_path(info.filename)
            if not path:
                continue
            if path in entries:
                raise ValidationError(f"duplicate archive path '{path}'", "E005")
            entries[path] = archive.read(info)
    return entries


def _tar_entries(data: bytes, limits: Limits) -> dict[str, bytes]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")  # noqa: SIM115
    except tarfile.TarError as exc:
        raise ValidationError("not a readable tar archive", "E001") from exc
    entries: dict[str, bytes] = {}
    total = 0
    with archive:
        for member in archive:
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise ValidationError(f"symlink in archive: {member.name}", "E006")
            if not member.isfile():
                continue
            path = _check_path(member.name)
            if not path:
                continue
            if len(entries) >= limits.max_files:
                raise LimitExceeded(f"archive holds more than {limits.max_files} files")
            total += member.size
            if total > limits.max_extracted_bytes:
                raise LimitExceeded(
                    f"archive unpacks to more than {limits.max_extracted_bytes} bytes"
                )
            handle = archive.extractfile(member)
            if handle is None:
                continue
            entries[path] = handle.read()
    return entries


def _strip_root(entries: dict[str, bytes]) -> dict[str, bytes]:
    roots = {p.split("/", 1)[0] for p in entries}
    if len(roots) != 1 or any("/" not in p for p in entries):
        return entries
    root = next(iter(roots))
    return {p[len(root) + 1 :]: c for p, c in entries.items()}
