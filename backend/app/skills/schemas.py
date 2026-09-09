"""Skill bundles — the SKILL.md text plus its supporting files, bounded."""

import base64
import binascii
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import SQLModel


MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
# The Agent Skills name rule: lowercase alphanumerics, single hyphens between.
NAME_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_PATH_CHARS = re.compile(r"[A-Za-z0-9_.\-/]+")


class SkillFile(BaseModel):
    """A supporting file, relative to the skill folder. Text is stored as-is,
    binaries base64-encoded (`encoding` says which)."""

    path: str = Field(min_length=1, max_length=240)
    # 10 MB of base64 — the byte budget is enforced on the whole bundle.
    content: str = Field(max_length=14_000_000)
    encoding: Literal["utf-8", "base64"] = "utf-8"

    @field_validator("path")
    @classmethod
    def _relative_without_traversal(cls, value: str) -> str:
        parts = value.split("/")
        if not _PATH_CHARS.fullmatch(value) or any(
            part in {"", ".", ".."} for part in parts
        ):
            raise ValueError(
                "must be a relative path of [A-Za-z0-9_.-/] characters "
                "with no empty, '.' or '..' segments"
            )
        if parts[0].lower() == "skill.md":
            raise ValueError("SKILL.md is the skill itself, not a supporting file")
        return value

    def bytes(self) -> bytes:
        if self.encoding == "utf-8":
            return self.content.encode("utf-8")
        try:
            return base64.b64decode(self.content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{self.path}: invalid base64 content") from exc


class SkillBundle(BaseModel):
    """One skill as the runtime consumes it, and as a run freezes it.

    `name` and `description` are what `bundles.parse_skill` read from the
    frontmatter of `content`; they travel alongside so a frozen copy is
    usable without re-parsing, and so the DB row's columns are filled from
    the same validated values.
    """

    name: str = Field(min_length=1, max_length=64, pattern=NAME_PATTERN)
    description: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=110_000)
    files: list[SkillFile] = Field(default_factory=list, max_length=MAX_FILES)

    @model_validator(mode="after")
    def _consistent_and_bounded(self) -> "SkillBundle":
        # Case-insensitive: the bundle is exported as a zip that may land on a
        # case-insensitive filesystem.
        paths = [file.path.casefold() for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate file paths")
        if any(other.startswith(path + "/") for path in paths for other in paths):
            raise ValueError("a file path cannot also be a directory")
        total = len(self.content.encode()) + sum(len(f.bytes()) for f in self.files)
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("skill exceeds 10 MB")
        return self


class SkillSave(BaseModel):
    """Create/update payload: the SKILL.md text and the files. `revision` is
    the revision the client last read — required on update, refused when
    stale, so two editors never silently overwrite each other."""

    content: str = Field(min_length=1, max_length=110_000)
    files: list[SkillFile] = Field(default_factory=list, max_length=MAX_FILES)
    revision: int | None = None


class SkillCreateDB(SQLModel):
    """Server-side create payload: a validated bundle's columns plus the owner."""

    owner_id: UUID
    name: str
    description: str
    content: str
    files: list[dict]


class SkillSummary(BaseModel):
    """A library row — everything but the document and its files."""

    id: UUID
    owner_id: UUID
    name: str
    description: str
    revision: int
    file_count: int
    updated_at: datetime
    can_edit: bool


class SkillResponse(SkillSummary):
    content: str
    files: list[SkillFile]


class AgentSkillResponse(BaseModel):
    """A skill enabled on an agent, as the agent detail response lists it."""

    id: UUID
    name: str
    description: str
