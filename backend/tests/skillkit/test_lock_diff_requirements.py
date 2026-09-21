from datetime import UTC, datetime

import pytest

from skillkit import (
    ArchiveSource,
    Bundle,
    EnvironmentManifest,
    Lockfile,
    LockfileError,
    bundle_digest,
    diff_bundles,
    parse_requirements,
    set_digest,
)
from tests.skillkit.conftest import skill_md, tar_bytes


def test_digest_is_content_only_and_order_free():
    a = {"SKILL.md": b"x", "scripts/run.py": b"y"}
    b = {"scripts/run.py": b"y", "SKILL.md": b"x"}
    assert bundle_digest(a) == bundle_digest(b)
    assert bundle_digest(a) != bundle_digest({**a, "scripts/run.py": b"z"})
    assert bundle_digest({"café.md": b""}) == bundle_digest({"café.md": b""})  # NFC
    assert set_digest(["b", "a"]) == set_digest(["a", "b"])


def test_lockfile_roundtrip_equality_and_diff(repo_tree):
    resolved = ArchiveSource(
        tar_bytes(repo_tree),
        url="https://github.com/acme/skills",
        ref="main",
        revision="aaa",
        kind="github",
    ).resolve()
    lock = Lockfile.from_resolved(
        resolved,
        skills=["weekly-brief", "margin-audit"],
        resolved_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    text = lock.dumps()
    assert (
        text.endswith("\n")
        and '"version": 1' in text
        and '"resolved_at": "2026-09-17T00:00:00Z"' in text
    )
    again = Lockfile.loads(text)
    assert (
        again == lock
        and again.sources[0].skills["margin-audit"].path == "skills/margin-audit"
    )
    with pytest.raises(LockfileError):
        Lockfile.from_resolved(resolved, skills=["nope"])
    with pytest.raises(LockfileError):
        Lockfile.loads('{"version": 2}')

    changed = dict(repo_tree)
    changed["skills/margin-audit/scripts/pivot.py"] = b"import polars\n"
    del changed["skills/weekly-brief/SKILL.md"]
    current = ArchiveSource(
        tar_bytes(changed),
        url="https://github.com/acme/skills",
        ref="main",
        revision="bbb",
        kind="github",
    ).resolve()
    diff = lock.diff(current)
    assert diff.revision_changed
    assert {s.name: s.status for s in diff.skills if s.status != "unchanged"} == {
        "margin-audit": "changed",
        "weekly-brief": "removed",
        "kyc-check": "added",
        "escalation-tone": "added",
        "commit-style": "added",
        # weekly-brief's SKILL.md is gone, so the SKILL.md nested under it is
        # no longer shadowed and becomes a skill at depth 3.
        "nested": "added",
    }


def test_diff_bundles_categories():
    old = Bundle(
        {
            "SKILL.md": skill_md(
                "m",
                "Recompute margins from raw exports. Use when margins look off.",
                body="# Steps\n\nOld.\n",
            ),
            "scripts/run.py": b"print(1)\n",
            "references/g.md": b"a",
            "assets/logo.png": b"\x89PNG\x00",
        }
    )
    new = Bundle(
        {
            "SKILL.md": skill_md(
                "m",
                "Recompute margins from raw exports. Use when finance asks for a margin audit.",
                body="# Steps\n\nOld.\n",
            ),
            "scripts/run.py": b"print(2)\n",
            "references/g.md": b"a",
            "assets/logo.png": b"\x89PNG\x01",
        }
    )
    d = diff_bundles("m", old, new)
    assert d.status == "changed"
    assert d.categories == ("description", "scripts", "assets")
    assert not d.instructions_changed
    by_path = {f.path: f for f in d.files}
    assert by_path["scripts/run.py"].unified.startswith("--- a/scripts/run.py")
    assert (
        by_path["assets/logo.png"].binary and by_path["assets/logo.png"].unified is None
    )
    assert diff_bundles("m", old, old).status == "unchanged"


def test_requirements_grammar_and_check():
    req = parse_requirements(
        "python>=3.11; pandas>=2.1, openpyxl; egress=none; wat?; image>=4"
    )
    assert str(req.python) == ">=3.11" and str(req.image) == ">=4"
    assert [str(r) for r in req.packages] == ["pandas>=2.1", "openpyxl"]
    assert req.egress == "none" and req.unknown == ("wat?",)

    env = EnvironmentManifest.from_dict(
        {
            "version": 1,
            "image": "ghcr.io/acme/runtime:4.2.0",
            "interpreter": {"language": "python", "version": "3.12.4"},
            "packages": {"pandas": "2.2.1", "OpenPyXL": "3.1.0"},
            "egress": "none",
        }
    )
    assert (verdict := __import__("skillkit").check(req, env)).runnable, verdict.reasons

    old_env = EnvironmentManifest.from_dict(
        {"interpreter": {"version": "3.10.1"}, "packages": {"pandas": "1.5.3"}}
    )
    verdict = __import__("skillkit").check(req, old_env)
    assert not verdict.runnable
    assert verdict.reasons == (
        "requires python>=3.11, environment has 3.10.1",
        "requires image>=4, environment declares no image version",
        "requires pandas>=2.1, environment has pandas 1.5.3",
        "requires openpyxl, environment does not have it",
    )
    assert __import__("skillkit").check(None, old_env).runnable
