"""Skill bundles — the SKILL.md text plus its supporting files, bounded."""

import base64
import binascii
import re
from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import SQLModel


MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
# The Agent Skills layout folder whose files are programs an agent runs. A
# skill with anything under it needs an agent that runs code; a skill without
# is instructions and references only, and applies to every agent.
SCRIPTS_DIR = "scripts"
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

    def file_bytes(self) -> dict[str, bytes]:
        """The skill as a tree relative to its folder: SKILL.md plus files."""
        return {
            "SKILL.md": self.content.encode(),
            **{f.path: f.bytes() for f in self.files},
        }

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
    """Server-side create payload: a validated bundle's columns plus the owner,
    and — for a sourced skill — where it came from."""

    owner_id: UUID
    name: str
    description: str
    content: str
    files: list[dict]
    digest: str | None = None
    source_id: UUID | None = None
    source_path: str | None = None
    source_revision: str | None = None


class SkillSummary(BaseModel):
    """A library row — everything but the document and its files.

    `script_count` is how many files sit under `scripts/`: zero means the
    skill runs on any agent, more means its scripts only run on an agent with
    code execution. `agent_count` is how many agents have it enabled — a
    skill in use cannot be deleted or renamed.

    Two provenances: an in-app skill (`source_id` None) is edited here and is
    live on the next run; a sourced skill is pinned to a content digest from
    its repository and adopts a newer version explicitly (`update_available`).
    `can_edit` is about the content (never for a sourced skill);
    `can_manage` is delete / adopt (owner or admin).
    """

    id: UUID
    owner_id: UUID
    name: str
    description: str
    revision: int
    file_count: int
    script_count: int
    agent_count: int
    updated_at: datetime
    can_edit: bool
    can_manage: bool = False
    source_id: UUID | None = None
    source_name: str | None = None
    source_path: str | None = None
    source_revision: str | None = None
    digest: str | None = None
    update_available: bool = False
    missing_upstream: bool = False


class SkillAgentRef(BaseModel):
    """An agent a skill is enabled on — enough to name and link it."""

    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None


class SkillVersionInfo(BaseModel):
    """A newer version of a sourced skill, waiting to be adopted."""

    digest: str
    revision: str
    discovered_at: datetime


class SkillResponse(SkillSummary):
    content: str
    files: list[SkillFile]
    agents: list[SkillAgentRef] = Field(default_factory=list)
    available: SkillVersionInfo | None = None


class SkillIssue(BaseModel):
    """One skillkit validation finding, as the API reports it."""

    code: str
    severity: Literal["error", "warning"]
    message: str
    path: str | None = None
    suggestion: str | None = None


class SkillFileChange(BaseModel):
    path: str
    status: Literal["added", "removed", "modified"]
    old_size: int | None
    new_size: int | None
    binary: bool
    unified: str | None = None


class SkillDiffResponse(BaseModel):
    """What changed between the adopted version of a sourced skill and the
    newest one its repository holds (skillkit's semantic diff)."""

    name: str
    status: Literal["changed", "unchanged"]
    old_digest: str
    new_digest: str
    old_revision: str | None
    new_revision: str | None
    categories: list[str]
    description_changed: bool
    instructions_changed: bool
    scripts_changed: bool
    requirements_changed: bool
    files: list[SkillFileChange]


# -- sources -------------------------------------------------------------------


class SkillSourceKind(str, Enum):
    github = "github"
    gitlab = "gitlab"


class SkillSourceCreate(BaseModel):
    """Connect a repository. `kind` is detected from the host for github.com
    and gitlab.com and required otherwise (a self-hosted instance)."""

    url: str = Field(min_length=8, max_length=500)
    kind: SkillSourceKind | None = None
    ref: str = Field(default="main", min_length=1, max_length=200)
    subpath: str | None = Field(default=None, max_length=240)
    token: str | None = Field(default=None, max_length=500)

    @field_validator("url")
    @classmethod
    def _https_repository(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("must be an https:// repository URL")
        return value

    @field_validator("subpath")
    @classmethod
    def _clean_subpath(cls, value: str | None) -> str | None:
        value = (value or "").strip().strip("/")
        return value or None


class SkillSourcePatch(BaseModel):
    ref: str | None = Field(default=None, min_length=1, max_length=200)
    subpath: str | None = Field(default=None, max_length=240)
    token: str | None = Field(default=None, max_length=500)
    clear_token: bool = False


class SkillSourceReportEntry(BaseModel):
    """A skill the last sync found but did not import, and why."""

    path: str
    name: str
    issues: list[SkillIssue]


class SkillSourceResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    kind: SkillSourceKind
    url: str
    ref: str
    subpath: str | None
    has_token: bool
    last_revision: str | None
    last_synced_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_report: list[SkillSourceReportEntry]
    skill_count: int
    can_manage: bool
    created_at: datetime | None
    updated_at: datetime


class SkillSourcePreviewSkill(BaseModel):
    name: str
    description: str
    path: str
    container: str
    script_count: int
    ok: bool
    issues: list[SkillIssue]


class SkillSourcePreview(BaseModel):
    """What a repository holds, before it is connected — the "test before
    adding" step."""

    kind: SkillSourceKind
    name: str
    revision: str
    skills: list[SkillSourcePreviewSkill]
    issues: list[SkillIssue]


class AgentSkillResponse(BaseModel):
    """A skill enabled on an agent, as the agent detail response lists it."""

    id: UUID
    name: str
    description: str
    script_count: int = 0


def is_script(path: str) -> bool:
    """Whether a supporting file is a script, by the layout: under `scripts/`."""
    return path.split("/", 1)[0] == SCRIPTS_DIR and "/" in path


def count_scripts(files: Iterable[SkillFile]) -> int:
    return sum(1 for file in files if is_script(file.path))
