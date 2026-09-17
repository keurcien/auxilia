"""Validation is a pure function over a bundle.

Codes are stable; messages are ours. Errors mean the skill must not be loaded;
warnings mean it will load but something is off. ``W001`` carries a fix
suggestion when a referenced file exists under another path — the case where
a SKILL.md says ``python new-script.py`` and the file is
``scripts/new-script.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from skillkit import frontmatter as fm
from skillkit.model import SKILL_MD, Bundle, Frontmatter, Issue, Limits, Report
from skillkit.requirements import REQUIRES_KEY, parse_requirements, requirements_text


MIN_DESCRIPTION = 40
_PATH_CHARS = re.compile(r"^[A-Za-z0-9_.\-/]+$")
_SCRIPT_EXT = (".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl", ".r")
# Words in the body that look like a file: contain a slash or a known extension.
_REFERENCE = re.compile(
    r"(?<![\w./-])((?:[\w.\-]+/)+[\w.\-]+|[\w\-]+\.(?:py|sh|bash|js|mjs|ts|rb|md|json|yaml|yml|csv|txt|sql|r))(?![\w/-])",
    re.IGNORECASE,
)
_URL_OR_SPECIAL = re.compile(
    r"^(https?:|mailto:|\d+\.\d+|e\.g|i\.e|etc\.)", re.IGNORECASE
)
_ESCAPE = re.compile(r"(^|[\s\"'=])(\.\./|/(?:tmp|usr|etc|home|var|opt|root)/)")


def path_issues(path: str) -> list[Issue]:
    """The rule for a supporting file's path: relative, safe characters, no
    empty, ``.`` or ``..`` segment."""
    parts = path.split("/")
    if not _PATH_CHARS.match(path) or any(p in {"", ".", ".."} for p in parts):
        return [
            Issue(
                "E005",
                "error",
                "path must be relative, [A-Za-z0-9_.-/] only, with no empty, '.' or '..' segment",
                path,
            )
        ]
    return []


def validate_bundle(
    bundle: Bundle,
    *,
    directory_name: str | None = None,
    limits: Limits = Limits(),
    parsed: tuple[Frontmatter | None, list[Issue]] | None = None,
) -> Report:
    """Every finding for one skill. ``directory_name`` enables the spec's
    "name must match the directory" rule; pass ``None`` for a skill that has
    no directory (authored in an app)."""
    issues: list[Issue] = []
    skill_md = bundle.skill_md
    if skill_md is None:
        return Report((Issue("E001", "error", f"{SKILL_MD} is missing"),))
    if len(skill_md) > limits.max_skill_md_bytes:
        return Report(
            (
                Issue(
                    "E001",
                    "error",
                    f"{SKILL_MD} is larger than {limits.max_skill_md_bytes} bytes",
                ),
            )
        )
    text = bundle.text(SKILL_MD)
    if text is None:
        return Report((Issue("E001", "error", f"{SKILL_MD} is not UTF-8 text"),))

    frontmatter, fm_issues = parsed if parsed is not None else fm.parse(text)
    issues.extend(fm_issues)
    if frontmatter is not None:
        if (
            directory_name is not None
            and frontmatter.name
            and frontmatter.name != directory_name
        ):
            issues.append(
                Issue(
                    "E003",
                    "error",
                    f"name '{frontmatter.name}' must match the directory name '{directory_name}'",
                )
            )
        if not frontmatter.body.strip():
            issues.append(
                Issue(
                    "E004", "error", "SKILL.md needs instructions after the frontmatter"
                )
            )
        if frontmatter.description and len(frontmatter.description) < MIN_DESCRIPTION:
            issues.append(
                Issue(
                    "W004",
                    "warning",
                    f"description is {len(frontmatter.description)} characters — say what the "
                    "skill does *and when to use it*; that sentence is how agents pick it",
                )
            )
        requirements = requirements_text(frontmatter)
        if requirements is not None:
            unknown = parse_requirements(requirements).unknown
            if unknown:
                issues.append(
                    Issue(
                        "W007",
                        "warning",
                        f"metadata.{REQUIRES_KEY}: could not parse "
                        + "; ".join(unknown),
                    )
                )
        issues.extend(_reference_issues(frontmatter.body, bundle.files))

    for path in bundle.files:
        if path == SKILL_MD:
            continue
        issues.extend(path_issues(path))
        if path.split("/", 1)[0].lower() == SKILL_MD.lower():
            issues.append(
                Issue("E005", "error", "SKILL.md is the skill itself, not a file", path)
            )
    issues.extend(_script_escape_issues(bundle))

    if len(bundle.files) > limits.max_skill_files:
        issues.append(
            Issue(
                "W005",
                "warning",
                f"{len(bundle.files)} files; the limit is {limits.max_skill_files}",
            )
        )
    if bundle.size > limits.max_skill_bytes:
        issues.append(
            Issue(
                "W005",
                "warning",
                f"{bundle.size} bytes; the limit is {limits.max_skill_bytes}",
            )
        )
    return Report(tuple(issues))


def duplicate_name_issues(names: Iterable[str]) -> list[Issue]:
    """``W003`` for every name that appears more than once in one source."""
    seen: dict[str, int] = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
    return [
        Issue(
            "W003", "warning", f"'{name}' is declared by {count} skills in this source"
        )
        for name, count in sorted(seen.items())
        if count > 1
    ]


def _reference_issues(body: str, files: dict[str, bytes]) -> list[Issue]:
    issues: list[Issue] = []
    by_basename: dict[str, list[str]] = {}
    for path in files:
        by_basename.setdefault(path.rsplit("/", 1)[-1].lower(), []).append(path)
    seen: set[str] = set()
    for match in _REFERENCE.finditer(body):
        ref = match[1].strip("./")
        if (
            not ref
            or ref in seen
            or _URL_OR_SPECIAL.match(ref)
            or ref.lower() == SKILL_MD.lower()
        ):
            continue
        seen.add(ref)
        if ref in files or any(p.lower() == ref.lower() for p in files):
            continue
        candidates = by_basename.get(ref.rsplit("/", 1)[-1].lower(), [])
        if candidates:
            issues.append(
                Issue(
                    "W001",
                    "warning",
                    f"instructions reference '{ref}', which is not in the skill; "
                    f"found '{candidates[0]}'",
                    SKILL_MD,
                    suggestion=candidates[0],
                )
            )
        elif "/" in ref:
            # Only flag path-like references; a bare `report.csv` is often an
            # output the skill produces, not a file it ships.
            issues.append(
                Issue(
                    "W001",
                    "warning",
                    f"instructions reference '{ref}', which is not in the skill",
                    SKILL_MD,
                )
            )
    return issues


def _script_escape_issues(bundle: Bundle) -> list[Issue]:
    issues: list[Issue] = []
    for path in bundle.files:
        if not (path.startswith("scripts/") or path.lower().endswith(_SCRIPT_EXT)):
            continue
        text = bundle.text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if _ESCAPE.search(line):
                issues.append(
                    Issue(
                        "W002",
                        "warning",
                        f"line {line_no} looks like it reaches outside the skill directory "
                        "(heuristic — review before trusting the skill to run alone)",
                        path,
                    )
                )
                break
    return issues
