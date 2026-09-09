"""SKILL.md parsing and archive import/export — pure functions."""

import base64
import io
import zipfile

import pytest

from app.exceptions import DomainValidationError
from app.skills.bundles import export_archive, import_archive, parse_skill
from app.skills.schemas import SkillFile
from tests.skills.conftest import skill_markdown


def test_parse_reads_name_and_description_and_keeps_the_whole_document():
    content = (
        "---\nname: web-research\ndescription: Research a topic\n"
        "license: MIT\nallowed-tools: read_file\n---\n\nSteps here.\n"
    )
    bundle = parse_skill(content)

    assert bundle.name == "web-research"
    assert bundle.description == "Research a topic"
    # Extra frontmatter keys survive verbatim — deepagents' SkillsMiddleware
    # reads license / compatibility / allowed-tools off the file at run time.
    assert "license: MIT" in bundle.content
    assert bundle.files == []


def test_parse_normalizes_windows_line_endings():
    bundle = parse_skill("---\r\nname: a\r\ndescription: b\r\n---\r\n\r\nBody\r\n")
    assert "\r" not in bundle.content
    assert bundle.name == "a"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# no frontmatter\n", "must start with YAML frontmatter"),
        ("---\nname: [\n---\nbody", "Invalid YAML"),
        ("---\n- a\n- b\n---\nbody", "must be a YAML mapping"),
        ("---\nname: a\ndescription: b\n---\n\n   \n", "needs instructions"),
        ("---\nname: Not Valid\ndescription: b\n---\nbody", "name:"),
        ("---\nname: a\n---\nbody", "description:"),
    ],
)
def test_parse_rejects_malformed_documents_as_400s(content, message):
    with pytest.raises(DomainValidationError, match=message):
        parse_skill(content)


@pytest.mark.parametrize(
    "path", ["../etc/passwd", "/abs", "a//b", "SKILL.md", "skill.md/x", "sp ace"]
)
def test_files_reject_unsafe_paths(path):
    """Enforced on the `SkillFile` type itself, so an API payload fails at
    parse time (422) and an archive entry through `import_archive` (400)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SkillFile(path=path, content="x")
    if path == "SKILL.md":
        return  # an archive holds one entry per name; the root *is* SKILL.md
    with pytest.raises(DomainValidationError, match="path"):
        import_archive(
            _zip({"s/SKILL.md": skill_markdown("s").encode(), f"s/{path}": b"x"}),
            "s.zip",
        )


def test_files_reject_duplicates_and_file_directory_conflicts():
    with pytest.raises(DomainValidationError, match="duplicate"):
        parse_skill(
            skill_markdown(),
            [SkillFile(path="a.py", content=""), SkillFile(path="A.py", content="")],
        )
    with pytest.raises(DomainValidationError, match="also be a directory"):
        parse_skill(
            skill_markdown(),
            [SkillFile(path="a", content=""), SkillFile(path="a/b", content="")],
        )


def test_bundle_size_is_capped_at_10mb():
    big = SkillFile(path="blob.bin", content="A" * (10 * 1024 * 1024 + 1))
    with pytest.raises(DomainValidationError, match="10 MB"):
        parse_skill(skill_markdown(), [big])


def _zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_import_zip_uses_the_skill_md_folder_as_root_and_base64s_binaries():
    data = _zip(
        {
            "my-skill/SKILL.md": skill_markdown("my-skill").encode(),
            "my-skill/scripts/run.py": b"print(1)\n",
            "my-skill/assets/logo.png": b"\x89PNG\x00\xff",
        }
    )
    bundle = import_archive(data, "my-skill.zip")

    assert bundle.name == "my-skill"
    by_path = {f.path: f for f in bundle.files}
    assert by_path["scripts/run.py"].content == "print(1)\n"
    assert by_path["assets/logo.png"].encoding == "base64"
    assert base64.b64decode(by_path["assets/logo.png"].content) == b"\x89PNG\x00\xff"


def test_import_bare_markdown():
    bundle = import_archive(skill_markdown("solo").encode("utf-8-sig"), "SKILL.md")
    assert bundle.name == "solo"
    assert not bundle.content.startswith("﻿")


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ({"a/SKILL.md": b"x", "b/SKILL.md": b"x"}, "exactly one SKILL.md"),
        ({"readme.txt": b"x"}, "exactly one SKILL.md"),
        ({"a/SKILL.md": b"x", "b/other.py": b"x"}, "outside the skill folder"),
        ({"a/SKILL.md": b"x", "a/../x.py": b"x"}, "Unsafe archive path"),
    ],
)
def test_import_rejects_bad_archives(entries, message):
    with pytest.raises(DomainValidationError, match=message):
        import_archive(_zip(entries), "bad.zip")


def test_import_rejects_non_zip_and_oversized_uploads():
    with pytest.raises(DomainValidationError, match="Not a zip"):
        import_archive(b"not a zip", "x.skill")
    with pytest.raises(DomainValidationError, match="exceeds 10 MB"):
        import_archive(b"0" * (10 * 1024 * 1024 + 1), "x.zip")


def test_export_round_trips_through_import():
    bundle = parse_skill(
        skill_markdown("round-trip"),
        [
            SkillFile(path="scripts/run.py", content="print(1)\n"),
            SkillFile(
                path="assets/b.bin",
                content=base64.b64encode(b"\x89PNG\xff").decode(),
                encoding="base64",
            ),
        ],
    )

    again = import_archive(export_archive(bundle), "round-trip.zip")

    assert again == bundle
    with zipfile.ZipFile(io.BytesIO(export_archive(bundle))) as archive:
        assert sorted(archive.namelist()) == [
            "round-trip/SKILL.md",
            "round-trip/assets/b.bin",
            "round-trip/scripts/run.py",
        ]
