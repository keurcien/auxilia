"""The data model: issues, frontmatter, bundles, skills, resolved sources.

Everything here is plain dataclasses over ``dict[str, bytes]``. Nothing knows
about agents, sandboxes or databases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from skillkit.digest import bundle_digest
from skillkit.errors import ValidationError


if TYPE_CHECKING:
    from skillkit.requirements import EnvironmentManifest, Requirements, Verdict

SKILL_MD = "SKILL.md"
Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    """One validation finding. ``code`` is stable (``E003``, ``W001``…) so a
    consumer can render its own copy or suppress selectively."""

    code: str
    severity: Severity
    message: str
    path: str | None = None
    #: A concrete fix when one is known (W001: the path that does exist).
    suggestion: str | None = None


@dataclass(frozen=True)
class Report:
    issues: tuple[Issue, ...] = ()

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Limits:
    """Caller-set bounds. Defaults match the ecosystem CLI; auxilia passes
    its own (10 MB / 100 files per skill)."""

    max_download_bytes: int = 10 * 1024 * 1024
    max_extracted_bytes: int = 25 * 1024 * 1024
    max_files: int = 1000
    max_skill_bytes: int = 10 * 1024 * 1024
    max_skill_files: int = 100
    max_skill_md_bytes: int = 10 * 1024 * 1024  # deepagents' MAX_SKILL_FILE_SIZE


@dataclass(frozen=True)
class Frontmatter:
    """The parsed YAML block. Only spec fields are typed; anything else is
    reported as an unknown key (skills-ref rejects those)."""

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()
    #: The body after the closing fence.
    body: str = ""

    @property
    def internal(self) -> bool:
        return self.metadata.get("internal", "").strip().lower() == "true"


@dataclass(frozen=True)
class Bundle:
    """The frozen bytes of one skill, keyed by POSIX path relative to the
    skill directory (``SKILL.md``, ``scripts/run.py``…).

    `frozen=True` stops the *field* being reassigned, not the dict behind it,
    and `digest` is cached — so a caller that mutated `files` afterwards left
    every hash, lockfile entry and diff describing content the bundle no
    longer held. The mapping is copied and wrapped on construction.
    """

    files: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @cached_property
    def digest(self) -> str:
        return bundle_digest(self.files)

    @property
    def skill_md(self) -> bytes | None:
        return self.files.get(SKILL_MD)

    def text(self, path: str) -> str | None:
        """The file as UTF-8 text, or ``None`` when absent or binary."""
        data = self.files.get(path)
        if data is None:
            return None
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None

    @property
    def size(self) -> int:
        return sum(len(data) for data in self.files.values())

    def __hash__(self) -> int:
        return hash(self.digest)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bundle) and self.files == other.files


@dataclass(frozen=True)
class Skill:
    """A discovered skill: where it was found, what it declares, its bytes."""

    name: str
    description: str
    #: Directory of the skill inside the source, POSIX, no trailing slash
    #: (``skills/report-builder``; ``""`` for a root skill).
    path: str
    #: The container that claimed it (``"skills"``, ``"skills/.curated"``,
    #: ``""`` for the root, ``"*"`` for a full-depth find).
    container: str
    frontmatter: Frontmatter | None
    bundle: Bundle
    report: Report
    limits: Limits = Limits()

    @property
    def internal(self) -> bool:
        return bool(self.frontmatter and self.frontmatter.internal)

    @property
    def directory_name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def digest(self) -> str:
        return self.bundle.digest

    def validate(self) -> Report:
        return self.report

    @cached_property
    def requirements(self) -> Requirements | None:
        from skillkit.requirements import parse_requirements, requirements_text

        text = requirements_text(self.frontmatter)
        return parse_requirements(text) if text is not None else None

    def check(self, env: EnvironmentManifest) -> Verdict:
        from skillkit.requirements import check

        return check(self.requirements, env)


@dataclass(frozen=True)
class ResolvedSource:
    """A source at one immutable revision."""

    kind: str
    url: str
    ref: str | None
    revision: str
    #: Every discovered skill, internal ones included.
    all_skills: tuple[Skill, ...]
    #: Source-level findings (duplicate names, dropped entries).
    issues: tuple[Issue, ...] = ()

    @property
    def skills(self) -> tuple[Skill, ...]:
        return tuple(s for s in self.all_skills if not s.internal)

    def get(self, name: str | None = None, *, path: str | None = None) -> Skill | None:
        for skill in self.all_skills:
            if (name is not None and skill.name == name) or (
                path is not None and skill.path == path.strip("/")
            ):
                return skill
        return None

    @property
    def by_name(self) -> dict[str, Skill]:
        """Skills by name.

        Duplicates are a caller error, not something to resolve by "last one
        wins" — silently dropping a skill is how a source ends up importing
        fewer skills than it reports. `discover` already flags the duplicate
        with W003; this refuses to paper over it.
        """
        by: dict[str, Skill] = {}
        for skill in self.skills:
            if skill.name in by:
                raise ValidationError(
                    f"duplicate skill name '{skill.name}' at "
                    f"'{by[skill.name].path}' and '{skill.path}'",
                    "E009",
                )
            by[skill.name] = skill
        return by
