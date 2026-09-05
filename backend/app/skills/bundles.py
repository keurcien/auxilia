"""Safe import/export of standard Agent Skills archives. Never extract to disk."""

import base64
import io
import stat
import zipfile

import yaml  # type: ignore[import-untyped]

from app.skills.schemas import MAX_BUNDLE_BYTES, SkillBundle, SkillFile


def skill_markdown(bundle: SkillBundle) -> str:
    metadata = {
        "name": bundle.name,
        "description": bundle.description,
        "metadata": {"auxilia-requires-code": str(bundle.requires_code).lower()},
    }
    return (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n\n"
        + bundle.instructions
    )


def export_bundle(bundle: SkillBundle) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{bundle.name}/SKILL.md", skill_markdown(bundle))
        for file in bundle.files:
            archive.writestr(f"{bundle.name}/{file.path}", file.bytes())
    return output.getvalue()


def import_bundle(data: bytes, filename: str) -> SkillBundle:
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError("Upload exceeds 10 MB")
    files = {}
    if filename.lower().endswith(".md"):
        files["SKILL.md"] = data
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 150
                or sum(i.file_size for i in entries) > MAX_BUNDLE_BYTES
            ):
                raise ValueError("Archive exceeds skill limits")
            for entry in entries:
                if entry.is_dir():
                    continue
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Symbolic links are not supported")
                path = entry.filename
                if (
                    path.startswith("/")
                    or "\\" in path
                    or any(p in {"", ".", ".."} for p in path.split("/"))
                ):
                    raise ValueError("Unsafe archive path")
                if path in files:
                    raise ValueError("Duplicate archive path")
                files[path] = archive.read(entry)
    roots = [p for p in files if p == "SKILL.md" or p.endswith("/SKILL.md")]
    if len(roots) != 1:
        raise ValueError("Import one bundle with exactly one SKILL.md")
    root = roots[0][: -len("SKILL.md")]
    markdown = files.pop(roots[0]).decode("utf-8-sig").replace("\r\n", "\n")
    parts = markdown.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("SKILL.md needs YAML frontmatter")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError("Invalid YAML frontmatter")
    resources = []
    for path, content in files.items():
        if not path.startswith(root):
            raise ValueError("Files must be inside the skill folder")
        try:
            resources.append(
                SkillFile(path=path[len(root) :], content=content.decode("utf-8"))
            )
        except UnicodeDecodeError:
            resources.append(
                SkillFile(
                    path=path[len(root) :],
                    content=base64.b64encode(content).decode(),
                    encoding="base64",
                )
            )
    metadata = meta.get("metadata", {})
    return SkillBundle(
        name=meta.get("name", ""),
        title=meta.get("name", ""),
        description=meta.get("description", ""),
        instructions=parts[2].strip(),
        files=resources,
        requires_code=any(f.path.startswith("scripts/") for f in resources)
        or (
            isinstance(metadata, dict)
            and metadata.get("auxilia-requires-code") == "true"
        ),
    )
