"""Fixture trees built in memory; archives written at test time."""

from __future__ import annotations

import io
import tarfile
import zipfile

import pytest


def skill_md(
    name: str,
    description: str = "Builds the thing. Use when asked for the thing.",
    body: str = "# Steps\n\n1. Do it.\n",
    extra: str = "",
) -> bytes:
    return (
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}".encode()
    )


@pytest.fixture
def repo_tree() -> dict[str, bytes]:
    """An upstream-shaped repository: flat skills, a category, a curated
    container, an internal skill, a nested SKILL.md that is a file of its
    parent, and an agent-specific directory."""
    return {
        "README.md": b"# skills\n",
        "skills/weekly-brief/SKILL.md": skill_md(
            "weekly-brief",
            "Format the Monday sales recap. Use when asked for the weekly brief.",
        ),
        "skills/margin-audit/SKILL.md": skill_md(
            "margin-audit",
            "Recompute margins from raw exports. Use when margins look off.",
            body="# Steps\n\nRun `python scripts/clean.py` then `scripts/pivot.py`.\n",
            extra='metadata:\n  auxilia-requires: "python>=3.11; pandas>=2.1; egress=none"\n',
        ),
        "skills/margin-audit/scripts/clean.py": b"import sys\nprint(sys.argv)\n",
        "skills/margin-audit/scripts/pivot.py": b"import pandas\n",
        "skills/margin-audit/references/guide.md": b"# Guide\n",
        "skills/margin-audit/assets/logo.png": b"\x89PNG\r\n\x1a\n\x00",
        "skills/finance/kyc-check/SKILL.md": skill_md(
            "kyc-check",
            "Run the KYC checklist on a new brand. Use when onboarding a brand.",
        ),
        "skills/.curated/escalation-tone/SKILL.md": skill_md(
            "escalation-tone",
            "How we speak to angry brands. Use when a brand escalates.",
        ),
        "skills/secret-sauce/SKILL.md": skill_md(
            "secret-sauce",
            "Internal only. Use never.",
            extra='metadata:\n  internal: "true"\n',
        ),
        "skills/weekly-brief/examples/nested/SKILL.md": skill_md(
            "nested", "A SKILL.md that is just a file of weekly-brief. Use never."
        ),
        ".claude/skills/commit-style/SKILL.md": skill_md(
            "commit-style", "Write commits the house way. Use when committing."
        ),
        "examples/outside/SKILL.md": skill_md(
            "outside", "Outside every container. Use only with full depth."
        ),
    }


def zip_bytes(tree: dict[str, bytes], root: str = "") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for path, content in tree.items():
            archive.writestr(f"{root}{path}", content)
    return out.getvalue()


def tar_bytes(tree: dict[str, bytes], root: str = "acme-skills-9f2c1ab/") -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for path, content in tree.items():
            info = tarfile.TarInfo(f"{root}{path}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return out.getvalue()
