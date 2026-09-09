"""SKILL.md parsing and Agent Skills archive import/export.

Pure functions: no database, no disk. Everything user-supplied is validated
here into a `SkillBundle`, and every rejection is a `DomainValidationError`
(a 400) — the service and router add nothing.
"""

import base64
import io
import re
import stat
import zipfile

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from app.exceptions import DomainValidationError
from app.skills.schemas import MAX_BUNDLE_BYTES, MAX_FILES, SkillBundle, SkillFile


# `---` fences around YAML, then the body. The closing fence may end the file.
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.DOTALL)
_SKILL_MD = "SKILL.md"


def parse_skill(content: str, files: list[SkillFile] | None = None) -> SkillBundle:
    """Validate SKILL.md text (and its files) into a bundle.

    Only `name` and `description` are read from the frontmatter — the two
    fields the standard requires. Any other key (`license`, `compatibility`,
    `metadata`, `allowed-tools`) stays in `content`, where deepagents'
    `SkillsMiddleware` reads and displays it at run time.
    """
    content = content.replace("\r\n", "\n")
    match = _FRONTMATTER.match(content)
    if match is None:
        raise DomainValidationError(
            "SKILL.md must start with YAML frontmatter between '---' lines, "
            "with at least `name` and `description`"
        )
    try:
        meta = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise DomainValidationError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise DomainValidationError("The frontmatter must be a YAML mapping")
    if not match[2].strip():
        raise DomainValidationError("SKILL.md needs instructions after the frontmatter")
    try:
        return SkillBundle(
            name=str(meta.get("name") or "").strip(),
            description=str(meta.get("description") or "").strip(),
            content=content,
            files=list(files or []),
        )
    except ValidationError as exc:
        raise DomainValidationError(_describe(exc)) from exc


def _describe(exc: ValidationError) -> str:
    """One readable line per failed field: `files.2.path: must be …`."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'skill'}: "
        f"{error['msg'].removeprefix('Value error, ')}"
        for error in exc.errors()
    )


def import_archive(data: bytes, filename: str) -> SkillBundle:
    """A skill from an upload: a bare `.md`, or a zip (`.zip` / `.skill`)
    holding exactly one SKILL.md at any depth — that folder becomes the
    skill root, every other entry a supporting file. Nothing is extracted to
    disk."""
    if len(data) > MAX_BUNDLE_BYTES:
        raise DomainValidationError("Upload exceeds 10 MB")
    if filename.lower().endswith(".md"):
        return parse_skill(_text(data))
    try:
        entries = _zip_entries(data)
    except zipfile.BadZipFile as exc:
        raise DomainValidationError("Not a zip archive") from exc
    roots = [p for p in entries if p == _SKILL_MD or p.endswith("/" + _SKILL_MD)]
    if len(roots) != 1:
        raise DomainValidationError("The archive must contain exactly one SKILL.md")
    root = roots[0][: -len(_SKILL_MD)]
    markdown = _text(entries.pop(roots[0]))
    files = []
    for path, content in entries.items():
        if not path.startswith(root):
            raise DomainValidationError(
                f"'{path}' is outside the skill folder '{root or '/'}'"
            )
        files.append(_skill_file(path[len(root) :], content))
    return parse_skill(markdown, files)


def export_archive(bundle: SkillBundle) -> bytes:
    """The bundle as a zip rooted at `<name>/`, the layout `import_archive`
    reads back and the one other Agent Skills tools expect."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{bundle.name}/{_SKILL_MD}", bundle.content)
        for file in bundle.files:
            archive.writestr(f"{bundle.name}/{file.path}", file.bytes())
    return output.getvalue()


def _zip_entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_FILES + 1:
            raise DomainValidationError(
                f"The archive holds more than {MAX_FILES} files"
            )
        if sum(info.file_size for info in infos) > MAX_BUNDLE_BYTES:
            raise DomainValidationError("The archive unpacks to more than 10 MB")
        entries: dict[str, bytes] = {}
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise DomainValidationError("Symbolic links are not supported")
            path = info.filename
            if path.startswith("/") or "\\" in path or ".." in path.split("/"):
                raise DomainValidationError(f"Unsafe archive path '{path}'")
            if path in entries:
                raise DomainValidationError(f"Duplicate archive path '{path}'")
            entries[path] = archive.read(info)
    return entries


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainValidationError("SKILL.md must be UTF-8 text") from exc


def _skill_file(path: str, content: bytes) -> SkillFile:
    try:
        text, encoding = content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = base64.b64encode(content).decode(), "base64"
    try:
        return SkillFile(path=path, content=text, encoding=encoding)
    except ValidationError as exc:
        raise DomainValidationError(_describe(exc)) from exc
