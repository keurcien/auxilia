"""What a skill's scripts need, and whether an environment provides it.

Declared in frontmatter as **one string** under ``metadata`` — the spec makes
``metadata`` a string → string map, skills-ref rejects unknown top-level
keys, and deepagents coerces nested values with ``str()``. So::

    metadata:
      auxilia-requires: "python>=3.11; pandas>=2.1, openpyxl; egress=none"

Grammar: ``;``-separated clauses. A clause is ``python<spec>``,
``image<spec>``, ``egress=none|allowlist|open``, or a ``,``-separated list of
PEP 508 requirements. Version specifiers are PEP 440. Unknown clauses are
kept in ``unknown`` (a warning), never a failure: the skill still loads, the
check just cannot vouch for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from skillkit.model import Frontmatter


REQUIRES_KEY = "auxilia-requires"
EGRESS_VALUES = ("none", "allowlist", "open")
_SPEC_CLAUSE = re.compile(r"^(python|image)\s*(.*)$")


@dataclass(frozen=True)
class Requirements:
    python: SpecifierSet | None = None
    image: SpecifierSet | None = None
    packages: tuple[Requirement, ...] = ()
    egress: str | None = None
    unknown: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.python or self.image or self.packages or self.egress)


@dataclass(frozen=True)
class EnvironmentManifest:
    """What an execution image provides. Generated in CI from the built image;
    this library only consumes the schema."""

    image: str | None = None
    image_version: Version | None = None
    language: str | None = None
    interpreter_version: Version | None = None
    packages: dict[str, Version] = field(default_factory=dict)
    runtime_installs: bool = False
    egress: str = "none"
    egress_allowlist: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> EnvironmentManifest:
        if int(data.get("version", 1)) != 1:
            raise ValueError(
                f"unsupported environment manifest version {data.get('version')}"
            )
        interpreter = data.get("interpreter") or {}
        image = data.get("image")
        return cls(
            image=image,
            image_version=_version(image.rsplit(":", 1)[-1])
            if image and ":" in image
            else None,
            language=interpreter.get("language"),
            interpreter_version=_version(interpreter.get("version")),
            packages={
                canonicalize_name(str(name)): v
                for name, raw in (data.get("packages") or {}).items()
                if (v := _version(raw)) is not None
            },
            runtime_installs=bool(data.get("runtime_installs", False)),
            egress=str(data.get("egress", "none")),
            egress_allowlist=tuple(data.get("egress_allowlist") or ()),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> EnvironmentManifest:
        text = Path(path).read_text("utf-8")
        data = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
        return cls.from_dict(data or {})


@dataclass(frozen=True)
class Verdict:
    runnable: bool
    reasons: tuple[str, ...] = ()


def requirements_text(frontmatter: Frontmatter | None) -> str | None:
    if frontmatter is None:
        return None
    value = frontmatter.metadata.get(REQUIRES_KEY)
    return value.strip() if value and value.strip() else None


def parse_requirements(text: str) -> Requirements:
    python = image = None
    packages: list[Requirement] = []
    egress = None
    unknown: list[str] = []
    for raw in text.split(";"):
        clause = raw.strip()
        if not clause:
            continue
        if clause.startswith("egress="):
            value = clause[len("egress=") :].strip().lower()
            if value in EGRESS_VALUES:
                egress = value
            else:
                unknown.append(clause)
            continue
        match = _SPEC_CLAUSE.match(clause)
        if match and (match[2] == "" or match[2][0] in "<>=!~"):
            try:
                spec = SpecifierSet(match[2])
            except InvalidSpecifier:
                unknown.append(clause)
                continue
            if match[1] == "python":
                python = spec
            else:
                image = spec
            continue
        parsed = []
        for item in clause.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                parsed.append(Requirement(item))
            except InvalidRequirement:
                parsed = []
                break
        if parsed:
            packages.extend(parsed)
        else:
            unknown.append(clause)
    return Requirements(
        python=python,
        image=image,
        packages=tuple(packages),
        egress=egress,
        unknown=tuple(unknown),
    )


def check(requirements: Requirements | None, env: EnvironmentManifest) -> Verdict:
    """Static comparison: whether the declared needs are met. It cannot know
    whether the script *works* — only a preflight in the real image can."""
    if requirements is None or requirements.empty:
        return Verdict(True)
    reasons: list[str] = []
    if requirements.python is not None:
        if env.interpreter_version is None:
            reasons.append(
                f"requires python{requirements.python}, environment declares no interpreter"
            )
        elif not requirements.python.contains(
            env.interpreter_version, prereleases=True
        ):
            reasons.append(
                f"requires python{requirements.python}, environment has {env.interpreter_version}"
            )
    if requirements.image is not None:
        if env.image_version is None:
            reasons.append(
                f"requires image{requirements.image}, environment declares no image version"
            )
        elif not requirements.image.contains(env.image_version, prereleases=True):
            reasons.append(
                f"requires image{requirements.image}, environment has {env.image_version}"
            )
    for req in requirements.packages:
        have = env.packages.get(canonicalize_name(req.name))
        if have is None:
            if not env.runtime_installs:
                reasons.append(f"requires {req}, environment does not have it")
        elif req.specifier and not req.specifier.contains(have, prereleases=True):
            reasons.append(f"requires {req}, environment has {req.name} {have}")
    if requirements.egress is not None and _egress_rank(
        requirements.egress
    ) > _egress_rank(env.egress):
        reasons.append(
            f"requires egress={requirements.egress}, environment allows {env.egress}"
        )
    return Verdict(not reasons, tuple(reasons))


def _egress_rank(value: str) -> int:
    return EGRESS_VALUES.index(value) if value in EGRESS_VALUES else 0


def _version(raw: object) -> Version | None:
    if raw is None:
        return None
    try:
        return Version(str(raw))
    except InvalidVersion:
        return None
