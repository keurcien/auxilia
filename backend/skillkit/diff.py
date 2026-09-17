"""Semantic diff between two versions of one skill.

``git diff`` is text; a UI and a CI gate need categories: did the *trigger*
(description) change, the instructions, the scripts (a trust event), the
requirements, or only references and assets? Each flag carries the per-file
diffs underneath. Binary files are reported with sizes, never diffed.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from skillkit import frontmatter as fm
from skillkit.model import SKILL_MD, Bundle
from skillkit.requirements import requirements_text


MAX_TEXT_DIFF_BYTES = 200 * 1024


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # added | removed | modified
    old_size: int | None
    new_size: int | None
    binary: bool
    unified: str | None = None


@dataclass(frozen=True)
class SkillDiff:
    name: str
    status: str  # changed | unchanged
    old_digest: str
    new_digest: str
    description_changed: bool = False
    instructions_changed: bool = False
    scripts_changed: bool = False
    requirements_changed: bool = False
    references_changed: bool = False
    assets_changed: bool = False
    other_changed: bool = False
    files: tuple[FileChange, ...] = field(default_factory=tuple)

    @property
    def categories(self) -> tuple[str, ...]:
        names = (
            ("description", self.description_changed),
            ("instructions", self.instructions_changed),
            ("scripts", self.scripts_changed),
            ("requirements", self.requirements_changed),
            ("references", self.references_changed),
            ("assets", self.assets_changed),
            ("other", self.other_changed),
        )
        return tuple(n for n, flag in names if flag)


def diff_bundles(name: str, old: Bundle, new: Bundle) -> SkillDiff:
    if old.digest == new.digest:
        return SkillDiff(name, "unchanged", old.digest, new.digest)

    files = tuple(_file_changes(old, new))
    flags = {
        "scripts_changed": False,
        "references_changed": False,
        "assets_changed": False,
        "other_changed": False,
    }
    for change in files:
        if change.path == SKILL_MD:
            continue
        top = change.path.split("/", 1)[0]
        key = {
            "scripts": "scripts_changed",
            "references": "references_changed",
            "assets": "assets_changed",
        }.get(top, "other_changed")
        flags[key] = True

    description_changed = instructions_changed = requirements_changed = False
    old_text, new_text = old.text(SKILL_MD), new.text(SKILL_MD)
    if old_text != new_text:
        old_fm, _ = fm.parse(old_text or "")
        new_fm, _ = fm.parse(new_text or "")
        if old_fm is None or new_fm is None:
            instructions_changed = True
            description_changed = bool(old_fm) != bool(new_fm) or (
                old_fm is not None
                and new_fm is not None
                and old_fm.description != new_fm.description
            )
        else:
            description_changed = old_fm.description != new_fm.description
            instructions_changed = old_fm.body.strip() != new_fm.body.strip()
            requirements_changed = (
                requirements_text(old_fm) != requirements_text(new_fm)
                or old_fm.compatibility != new_fm.compatibility
            )
            if (
                not description_changed
                and not instructions_changed
                and not requirements_changed
                and (old_fm.metadata, old_fm.license, old_fm.allowed_tools)
                != (new_fm.metadata, new_fm.license, new_fm.allowed_tools)
            ):
                flags["other_changed"] = True

    return SkillDiff(
        name,
        "changed",
        old.digest,
        new.digest,
        description_changed=description_changed,
        instructions_changed=instructions_changed,
        requirements_changed=requirements_changed,
        files=files,
        **flags,
    )


def _file_changes(old: Bundle, new: Bundle):
    for path in sorted(set(old.files) | set(new.files)):
        before, after = old.files.get(path), new.files.get(path)
        if before == after:
            continue
        status = (
            "added" if before is None else "removed" if after is None else "modified"
        )
        old_text = _text(before)
        new_text = _text(after)
        binary = (before is not None and old_text is None) or (
            after is not None and new_text is None
        )
        unified = None
        if (
            not binary
            and (len(before or b"") + len(after or b"")) <= MAX_TEXT_DIFF_BYTES
        ):
            unified = "".join(
                difflib.unified_diff(
                    (old_text or "").splitlines(keepends=True),
                    (new_text or "").splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        yield FileChange(
            path,
            status,
            None if before is None else len(before),
            None if after is None else len(after),
            binary,
            unified,
        )


def _text(data: bytes | None) -> str | None:
    if data is None:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
