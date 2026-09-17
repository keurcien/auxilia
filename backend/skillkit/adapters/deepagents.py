"""Hand skill bundles to deepagents.

The only module in the package that imports deepagents. It produces the two
things ``SkillsMiddleware`` and the filesystem tools need: the flattened
layout ``<root>/<name>/<file>`` (deepagents walks one level: every skill is
mounted at its *name*, whatever its path in the repo) and a read-only
in-memory backend over it, so nothing lands in a checkpoint or on a disk.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    FileUploadResponse,
    WriteResult,
)
from deepagents.backends.state import StateBackend
from deepagents.backends.utils import create_file_data


READ_ONLY = "Skill files are read-only. Copy the file elsewhere to change it."


def skill_files(
    skills: Mapping[str, Mapping[str, bytes]], root: str
) -> dict[str, bytes]:
    """``{name: {relative path: bytes}}`` → ``{absolute path: bytes}`` under
    ``root``, one folder per skill named after the skill."""
    files: dict[str, bytes] = {}
    for name, bundle in skills.items():
        for path, content in bundle.items():
            files[f"{root.rstrip('/')}/{name}/{path}"] = content
    return files


class InMemorySkillsBackend(StateBackend):
    """A read-only, in-memory backend over a fixed set of files.

    Inherits deepagents' in-state file semantics (``ls``, ``read``, ``glob``,
    ``grep``, ``download_files``) but reads a fixed mapping instead of the
    graph's ``files`` channel, so it works outside a graph context and
    writes nothing anywhere. Every write returns an error result.
    """

    def __init__(self, files: Mapping[str, bytes]) -> None:
        super().__init__()
        self._files = {path: _file_data(content) for path, content in files.items()}

    def _read_files(self) -> dict:
        return self._files

    def _send_files_update(self, update: dict) -> None:  # pragma: no cover - guarded
        raise RuntimeError(READ_ONLY)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=READ_ONLY)

    def edit(self, file_path, old_string, new_string, replace_all=False) -> EditResult:
        return EditResult(error=READ_ONLY)

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=READ_ONLY)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error=READ_ONLY) for path, _ in files]


def _file_data(content: bytes):
    try:
        return create_file_data(content.decode("utf-8"))
    except UnicodeDecodeError:
        return create_file_data(base64.b64encode(content).decode(), encoding="base64")
