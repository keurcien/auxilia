"""Split and parse ``SKILL.md`` frontmatter, per the Agent Skills spec.

The rules are the spec's (and skills-ref's, which is the reference
validator): ``name`` 1–64 chars of lowercase Unicode alphanumerics and single
hyphens, ``description`` 1–1024 chars, ``compatibility`` ≤ 500,
``metadata`` a string → string map, ``allowed-tools`` a space-separated
string, and **no other top-level key**. deepagents parses the same fields
but warns and truncates; here every deviation is an ``Issue`` so a repo can
be gated in CI before an agent ever sees it.
"""

from __future__ import annotations

import re

import yaml  # type: ignore[import-untyped]

from skillkit.model import Frontmatter, Issue


MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
KNOWN_KEYS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

# ``---`` fences around YAML, then the body. The closing fence may end the file.
_FENCES = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL
)


def split(content: str) -> tuple[str, str] | None:
    """``(yaml_text, body)`` or ``None`` when there is no frontmatter block."""
    match = _FENCES.match(content)
    return (match[1], match[2]) if match else None


def parse(content: str) -> tuple[Frontmatter | None, list[Issue]]:
    """Parse the document. Returns the frontmatter (``None`` when it cannot
    be read at all) and every issue found, errors and warnings alike."""
    issues: list[Issue] = []
    parts = split(content)
    if parts is None:
        return None, [
            Issue(
                "E002",
                "error",
                "SKILL.md must start with YAML frontmatter between '---' lines",
            )
        ]
    yaml_text, body = parts
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [Issue("E002", "error", f"Frontmatter is not valid YAML: {exc}")]
    if not isinstance(data, dict):
        return None, [Issue("E002", "error", "Frontmatter must be a YAML mapping")]

    name = _string(data.get("name"))
    description = _string(data.get("description"))
    issues.extend(validate_name(name))
    issues.extend(validate_description(description))

    unknown = tuple(sorted(str(k) for k in data if str(k) not in KNOWN_KEYS))
    if unknown:
        issues.append(
            Issue(
                "E007",
                "error",
                "Unknown frontmatter key(s): "
                + ", ".join(unknown)
                + " — the Agent Skills spec allows only "
                + ", ".join(sorted(KNOWN_KEYS)),
            )
        )

    metadata: dict[str, str] = {}
    raw_metadata = data.get("metadata")
    if raw_metadata is not None:
        if not isinstance(raw_metadata, dict):
            issues.append(Issue("E008", "error", "metadata must be a mapping"))
        else:
            for key, value in raw_metadata.items():
                if isinstance(value, (dict, list)) or value is None:
                    issues.append(
                        Issue(
                            "E008",
                            "error",
                            f"metadata.{key} must be a string, not "
                            f"{type(value).__name__} (the spec maps strings to strings)",
                        )
                    )
                    continue
                metadata[str(key)] = str(value)

    compatibility = _string(data.get("compatibility")) or None
    if compatibility and len(compatibility) > MAX_COMPATIBILITY:
        issues.append(
            Issue(
                "W006",
                "warning",
                f"compatibility is {len(compatibility)} characters; the spec limit is "
                f"{MAX_COMPATIBILITY} (agents may truncate it)",
            )
        )

    raw_tools = data.get("allowed-tools")
    allowed_tools: tuple[str, ...] = ()
    if isinstance(raw_tools, str):
        allowed_tools = tuple(raw_tools.split())
    elif isinstance(raw_tools, list):
        allowed_tools = tuple(str(t) for t in raw_tools)

    return (
        Frontmatter(
            name=name,
            description=description,
            license=_string(data.get("license")) or None,
            compatibility=compatibility,
            metadata=metadata,
            allowed_tools=allowed_tools,
            unknown_keys=unknown,
            body=body,
        ),
        issues,
    )


def validate_name(name: str, directory_name: str | None = None) -> list[Issue]:
    """The spec's name rule (same as deepagents' ``_validate_skill_name`` and
    skills-ref): lowercase Unicode alphanumerics and hyphens, no leading,
    trailing or double hyphen, ≤ 64 chars, equal to the directory name."""
    if not name:
        return [Issue("E003", "error", "name is required")]
    problems: list[str] = []
    if len(name) > MAX_NAME:
        problems.append(f"exceeds {MAX_NAME} characters")
    if name.startswith("-") or name.endswith("-") or "--" in name:
        problems.append("must not start or end with '-' or contain '--'")
    if not all(c == "-" or (c.isalpha() and c.islower()) or c.isdigit() for c in name):
        problems.append("must be lowercase letters, digits and hyphens only")
    if directory_name is not None and name != directory_name:
        problems.append(f"must match the directory name '{directory_name}'")
    if not problems:
        return []
    return [Issue("E003", "error", f"name '{name}' " + "; ".join(problems))]


def validate_description(description: str) -> list[Issue]:
    if not description:
        return [Issue("E004", "error", "description is required")]
    if len(description) > MAX_DESCRIPTION:
        return [
            Issue(
                "E004",
                "error",
                f"description is {len(description)} characters; the spec limit is "
                f"{MAX_DESCRIPTION}",
            )
        ]
    return []


def _string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
