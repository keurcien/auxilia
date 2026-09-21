"""SKILL.md parsing and validation — pure functions."""

import pytest

from app.exceptions import DomainValidationError
from app.skills.bundles import parse_skill
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
    """Enforced on the `SkillFile` type itself, so an API payload carrying one
    fails at parse time (422) and a synced bundle is refused (400)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SkillFile(path=path, content="x")


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
