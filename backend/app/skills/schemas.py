"""Portable, bounded skill bundles shared by the API, tools and runtime."""

import base64
import binascii
import hashlib
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_BUNDLE_BYTES = 10 * 1024 * 1024


class SkillFile(BaseModel):
    path: str = Field(max_length=240)
    content: str = Field(max_length=14_000_000)
    encoding: Literal["utf-8", "base64"] = "utf-8"

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if (
            not re.fullmatch(r"[a-zA-Z0-9_.\-/]+", value)
            or any(p in {"", ".", ".."} for p in value.split("/"))
            or value.split("/")[0].lower() == "skill.md"
        ):
            raise ValueError(
                "Use a relative file path without traversal; SKILL.md is managed separately"
            )
        return value

    def bytes(self) -> bytes:
        if self.encoding == "utf-8":
            return self.content.encode("utf-8")
        try:
            return base64.b64decode(self.content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid base64 file content") from exc


class SkillBundle(BaseModel):
    name: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    description: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=100000)
    files: list[SkillFile] = Field(default_factory=list, max_length=100)
    content: str | None = Field(default=None, max_length=110000)

    @model_validator(mode="after")
    def validate_bundle(self):
        paths = [f.path.casefold() for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate file paths")
        if any(any(other.startswith(path + "/") for other in paths) for path in paths):
            raise ValueError("A file cannot also be a directory")
        if (
            sum(len(f.bytes()) for f in self.files) + len(self.instructions.encode())
            > MAX_BUNDLE_BYTES
        ):
            raise ValueError("Skill bundle exceeds 10 MB")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class SkillSave(BaseModel):
    content: str = Field(min_length=1, max_length=110000)
    files: list[SkillFile] = Field(default_factory=list, max_length=100)
    revision: int | None = None


class SkillResponse(BaseModel):
    id: UUID
    owner_id: UUID
    revision: int
    name: str
    description: str
    instructions: str
    content: str
    files: list[SkillFile]
    can_edit: bool
