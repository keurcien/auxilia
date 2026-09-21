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
# Files in a whole *repository* archive, not in one skill. A source is often a
# monorepo whose skills sit under `subpath`, and the archive is fetched whole
# before anything is filtered, so this counts everything the repository holds.
# `MAX_BUNDLE_BYTES` is the real resource bound; this only stops a pathological
# tree. Keep it far above MAX_FILES — conflating the two capped every source at
# one skill's worth of files.
MAX_SOURCE_FILES = 20_000
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
    source_url: str | None = None
    source_path: str | None = None
    source_revision: str | None = None


class SkillSourceKind(str, Enum):
    github = "github"
    gitlab = "gitlab"


class SkillAgentRef(BaseModel):
    """An agent a skill is enabled on — enough to name and link it."""

    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None


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
    # The same agents `agent_count` counts, for the library's avatar stack.
    agents: list[SkillAgentRef] = []
    updated_at: datetime
    can_edit: bool
    can_manage: bool = False
    source_id: UUID | None = None
    source_name: str | None = None
    # Which host, so the library can show its mark next to the repository.
    source_kind: SkillSourceKind | None = None
    # The repository it came from, which outlives the link: a detached skill
    # has no `source_id` and no `source_name`, and this is what still names
    # the repository to connect again.
    source_url: str | None = None
    source_path: str | None = None
    source_revision: str | None = None
    digest: str | None = None
    update_available: bool = False
    missing_upstream: bool = False


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


class SkillSyncEntry(BaseModel):
    """One skill in a sync plan — what syncing would do to it.

    `unchanged` and `updated` both leave the live skill alone: a sync only
    makes a new version *available*, and adopting it is a separate, per-skill
    decision. `new` is the one status that changes the library on the spot,
    and `gone` only flags the skill — it keeps working, pinned.
    """

    name: str
    path: str
    status: Literal["new", "updated", "unchanged", "gone", "skipped"]
    script_count: int = 0
    issues: list[SkillIssue] = []


class SkillSyncPlan(BaseModel):
    """What a sync would do, computed without writing anything."""

    revision: str
    current_revision: str | None = None
    entries: list[SkillSyncEntry] = []


def normalize_repo_url(value: str) -> str:
    """One spelling per repository.

    The URL is an identity in two places — a source *is* its (url, ref, path),
    and a detached skill is reclaimed by the repository whose url it carries —
    so the three spellings a host hands out for the same repository must
    collapse to one. Without this, connecting `…/skills.git` after having
    connected `…/skills` is a different repository: a second source, and the
    skills the first one left behind are never reclaimed, only reported as
    names already taken. The user did nothing wrong and cannot see why.

    Deliberately conservative — trailing slashes and a trailing `.git`, and
    nothing that could change *which* server is addressed. The same
    transformation has to be expressible in SQL for the migration that
    normalises the rows already stored.
    """
    return value.strip().rstrip("/").removesuffix(".git").rstrip("/")


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
        value = normalize_repo_url(value)
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
    """What the last sync did to one skill — the whole story, not only the
    failures. A sync is the one operation here that changes the library
    without anyone watching it, so what it decided has to survive it; the
    plan answers "what will happen?" and this answers "what happened?".

    `status` defaults to `skipped` for rows written before the report carried
    every decision, which is what those rows held.
    """

    path: str
    name: str
    status: Literal["new", "updated", "unchanged", "gone", "skipped"] = "skipped"
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
