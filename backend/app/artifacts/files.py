"""Bounded binary extraction, performed inside the execution sandbox.

Never read a model-provided path from the Auxilia host filesystem. Walk with
openat/O_NOFOLLOW so symlink swaps cannot escape the allowed output roots.
"""

import base64
import io
import json
import shlex
import zipfile
from pathlib import PurePosixPath

from deepagents.backends.sandbox import BaseSandbox

from app.exceptions import DomainValidationError


PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class SandboxFileMissingError(Exception):
    pass


class SandboxReadError(Exception):
    """The sandbox could not be reached or failed to run the read."""


READ_SCRIPT = r"""
import os, stat, sys, base64, json
path, roots, limit = json.loads(sys.argv[1])
if not path.startswith('/') or '..' in path.split('/'):
    raise ValueError('Absolute output path required; traversal is forbidden')
path = os.path.normpath(path)
if not any(path.startswith(root.rstrip('/') + '/') for root in roots):
    raise ValueError('File must be in an allowed output directory')
fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
try:
    parts = path.strip('/').split('/')
    for part in parts[:-1]:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = child
    file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file_fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Not a regular file or file exceeds artifact size limit')
        data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError('File exceeds artifact size limit')
    print(base64.b64encode(data).decode('ascii'))
except FileNotFoundError:
    sys.exit(44)
finally:
    os.close(fd)
"""


def read_bytes(backend: BaseSandbox, path: str, roots: list[str], limit: int) -> bytes:
    args = json.dumps([path, roots, limit])
    command = f"python3 -c {shlex.quote(READ_SCRIPT)} {shlex.quote(args)}"
    try:
        # Runs inside the sandbox shell, not SQL; args are shlex-quoted JSON.
        result = backend.execute(command, timeout=60)  # nosemgrep
    except Exception as exc:  # provider SDKs raise their own transport errors
        raise SandboxReadError(path) from exc
    if result.exit_code == 44:
        raise SandboxFileMissingError(path)
    if result.exit_code != 0 or result.truncated:
        raise DomainValidationError(
            "Cannot read artifact: use a regular file in an allowed output directory within the size limit (symlinks are not supported)."
        )
    try:
        data = base64.b64decode(result.output.strip(), validate=True)
    except ValueError as exc:
        raise DomainValidationError("Sandbox returned an invalid artifact") from exc
    if len(data) > limit:
        raise DomainValidationError("Artifact exceeds the size limit")
    return data


def detect_mime(filename: str, data: bytes) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".pptx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 10000
                    or sum(x.file_size for x in entries) > 100 * 1024 * 1024
                ):
                    raise DomainValidationError(
                        "Presentation expands beyond the preview limit"
                    )
                if "ppt/presentation.xml" not in archive.namelist():
                    raise DomainValidationError("Invalid PowerPoint presentation")
        except zipfile.BadZipFile as exc:
            raise DomainValidationError("Invalid PowerPoint presentation") from exc
        return PPTX_MIME
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "application/pdf"
    types = {
        ".html": "text/html",
        ".htm": "text/html",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
        ".py": "text/x-python",
        ".js": "text/javascript",
    }
    if suffix in types:
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DomainValidationError("Text previews require UTF-8 files") from exc
        return types[suffix]
    return "application/octet-stream"
