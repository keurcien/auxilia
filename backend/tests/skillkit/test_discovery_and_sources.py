import pytest

from skillkit import ArchiveSource, LimitExceeded, LocalSource, ValidationError
from skillkit.discovery import discover
from skillkit.model import Limits
from tests.skillkit.conftest import skill_md, tar_bytes, zip_bytes


def test_discover_follows_the_ecosystem_layout(repo_tree):
    found = {f.path: f for f in discover(repo_tree)}
    assert set(found) == {
        "skills/weekly-brief",
        "skills/margin-audit",
        "skills/finance/kyc-check",  # one category level
        "skills/.curated/escalation-tone",  # dot container, claimed first
        "skills/secret-sauce",  # internal skills are discovered, flagged later
        ".claude/skills/commit-style",
    }
    assert found["skills/.curated/escalation-tone"].container == "skills/.curated"
    assert found["skills/finance/kyc-check"].container == "skills"
    # The nested SKILL.md is a *file* of weekly-brief, not a skill.
    assert "examples/nested/SKILL.md" in found["skills/weekly-brief"].files
    assert "skills/weekly-brief/examples/nested" not in found


def test_full_depth_and_subpath(repo_tree):
    deep = {f.path: f.container for f in discover(repo_tree, full_depth=True)}
    assert deep["examples/outside"] == "*"
    assert "skills/weekly-brief/examples/nested" not in deep  # still shadowed
    sub = discover(repo_tree, subpath="skills/finance")
    assert [
        f.path for f in sub
    ] == []  # `kyc-check` is at the new root's depth 1, but under no container
    sub_root = discover(
        {
            "SKILL.md": skill_md(
                "root-skill", "The repo is one skill. Use when the repo is one skill."
            ),
            "scripts/a.py": b"",
        }
    )
    assert sub_root[0].path == "" and "scripts/a.py" in sub_root[0].files


def test_archive_source_resolves_a_hosted_tarball(repo_tree):
    resolved = ArchiveSource(
        tar_bytes(repo_tree),
        filename="x.tar.gz",
        url="https://example/acme/skills",
        revision="9f2c1ab",
    ).resolve()
    assert resolved.revision == "9f2c1ab"
    names = {s.name for s in resolved.skills}
    assert names == {
        "weekly-brief",
        "margin-audit",
        "kyc-check",
        "escalation-tone",
        "commit-style",
    }
    assert resolved.get("secret-sauce").internal and "secret-sauce" not in names
    margin = resolved.get("margin-audit")
    assert margin.report.ok and margin.requirements.egress == "none"
    assert margin.bundle.digest.startswith("sha256:")
    assert resolved.issues == ()


def test_archive_source_rejects_unsafe_entries():
    with pytest.raises(ValidationError) as excinfo:
        ArchiveSource(zip_bytes({"../evil/SKILL.md": b"x"})).resolve()
    assert excinfo.value.code == "E005"
    with pytest.raises(LimitExceeded):
        ArchiveSource(
            zip_bytes({f"skills/s/{i}.txt": b"x" for i in range(5)}),
            limits=Limits(max_files=3),
        ).resolve()
    with pytest.raises(LimitExceeded):
        ArchiveSource(b"0" * 100, limits=Limits(max_download_bytes=10)).resolve()


def test_zip_of_one_skill_without_root_strip_matches_the_app_import():
    data = zip_bytes(
        {
            "my-skill/SKILL.md": skill_md(
                "my-skill", "One skill, exported by another tool. Use when imported."
            ),
            "my-skill/scripts/run.py": b"",
        }
    )
    resolved = ArchiveSource(data, full_depth=True, strip_root=False).resolve()
    [skill] = resolved.skills
    assert skill.path == "my-skill" and skill.container == "*"
    assert set(skill.bundle.files) == {"SKILL.md", "scripts/run.py"}


def test_local_source_reads_a_directory_and_refuses_symlinks(tmp_path, repo_tree):
    for path, content in repo_tree.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    resolved = LocalSource(tmp_path).resolve()
    assert resolved.revision.startswith("local:sha256:")
    assert resolved.get("kyc-check") is not None
    (tmp_path / "skills" / "link").symlink_to(tmp_path / "skills" / "weekly-brief")
    with pytest.raises(ValidationError) as excinfo:
        LocalSource(tmp_path).resolve()
    assert excinfo.value.code == "E006"
