"""SKILL.md parsing and validation — over skillkit.

Pure functions: no database, no disk. Everything user-supplied is validated
into a `SkillBundle`, and every rejection is a `DomainValidationError`
(a 400) — the service and router add nothing. The rules themselves live in
``skillkit`` (the spec's frontmatter rules, path safety, bounded bundles);
this module maps its issues and exceptions onto the app's error type and
the app's ``SkillBundle`` shape.
"""

from __future__ import annotations

import base64

from pydantic import ValidationError

from app.exceptions import DomainValidationError
from app.skills.schemas import (
    MAX_BUNDLE_BYTES,
    MAX_FILES,
    MAX_SOURCE_FILES,
    SkillBundle,
    SkillFile,
)
from skillkit import Bundle, Limits, frontmatter as fm
from skillkit.model import SKILL_MD
from skillkit.validate import validate_bundle


# The app's bounds, passed to skillkit rather than duplicated there.
LIMITS = Limits(
    max_download_bytes=MAX_BUNDLE_BYTES,
    max_extracted_bytes=MAX_BUNDLE_BYTES,
    max_files=MAX_SOURCE_FILES,  # the whole repository tree
    max_skill_bytes=MAX_BUNDLE_BYTES,
    max_skill_files=MAX_FILES,
)


def parse_skill(content: str, files: list[SkillFile] | None = None) -> SkillBundle:
    """Validate SKILL.md text (and its files) into a bundle.

    Only `name` and `description` are read from the frontmatter — the two
    fields the standard requires. Any other spec key (`license`,
    `compatibility`, `metadata`, `allowed-tools`) stays in `content`, where
    deepagents' `SkillsMiddleware` reads and displays it at run time. Keys
    the spec does not know are refused, as ``skills-ref`` refuses them. No
    directory-name rule here: an in-app skill has no directory.
    """
    content = content.replace("\r\n", "\n")
    files = list(files or [])
    bundle = Bundle({SKILL_MD: content.encode(), **{f.path: f.bytes() for f in files}})
    parsed = fm.parse(content)
    report = validate_bundle(bundle, limits=LIMITS, parsed=parsed)
    if not report.ok:
        raise DomainValidationError(
            "; ".join(_wording(i.message) for i in report.errors)
        )
    frontmatter = parsed[0]
    if frontmatter is None:
        # Unreachable: an unreadable frontmatter is already an error above.
        # Stated as a raise, not an `assert` — asserts vanish under -O.
        raise DomainValidationError("Invalid YAML frontmatter")
    try:
        return SkillBundle(
            name=frontmatter.name,
            description=frontmatter.description,
            content=content,
            files=files,
        )
    except ValidationError as exc:
        raise DomainValidationError(_describe(exc)) from exc


def _wording(message: str) -> str:
    """skillkit's messages, in the words this API always used: field errors
    read `name: …` / `description: …`, like the pydantic ones."""
    for field in ("name", "description"):
        if message.startswith(field + " "):
            message = f"{field}: {message[len(field) + 1 :]}"
    return (
        message.replace("Frontmatter is not valid YAML", "Invalid YAML frontmatter")
        .replace(
            "Frontmatter must be a YAML mapping",
            "The frontmatter must be a YAML mapping",
        )
        .replace("unsafe archive path", "Unsafe archive path")
        .replace("duplicate archive path", "Duplicate archive path")
    )


def _describe(exc: ValidationError) -> str:
    """One readable line per failed field: `files.2.path: must be …`."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'skill'}: "
        f"{error['msg'].removeprefix('Value error, ')}"
        for error in exc.errors()
    )


def skill_file_from_bytes(path: str, content: bytes) -> SkillFile:
    """A `SkillFile` from raw bytes: text when UTF-8, base64 otherwise."""
    return _skill_file(path, content)


def _skill_file(path: str, content: bytes) -> SkillFile:
    try:
        text, encoding = content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = base64.b64encode(content).decode(), "base64"
    try:
        return SkillFile(path=path, content=text, encoding=encoding)
    except ValidationError as exc:
        raise DomainValidationError(_describe(exc)) from exc
