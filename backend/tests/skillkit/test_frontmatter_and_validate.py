from skillkit import frontmatter as fm
from skillkit.model import Bundle
from skillkit.validate import duplicate_name_issues, validate_bundle
from tests.skillkit.conftest import skill_md


def codes(issues):
    return sorted(i.code for i in issues)


def test_parse_reads_spec_fields_and_body():
    parsed, issues = fm.parse(
        "---\nname: report\ndescription: Write the report. Use when asked for the weekly report.\n"
        "license: MIT\ncompatibility: Requires Python 3.11+\nallowed-tools: Bash(git:*) Read\n"
        'metadata:\n  author: acme\n  version: "1.0"\n---\n\n# Steps\n'
    )
    assert issues == []
    assert parsed.name == "report" and parsed.license == "MIT"
    assert parsed.allowed_tools == ("Bash(git:*)", "Read")
    assert parsed.metadata == {"author": "acme", "version": "1.0"}
    assert parsed.body.strip() == "# Steps"


def test_parse_rejects_unknown_keys_and_nested_metadata():
    parsed, issues = fm.parse(
        "---\nname: report\ndescription: Write the report. Use when asked for the report today.\n"
        "requires:\n  pandas: '>=2.1'\nmetadata:\n  skillkit:\n    requires: x\n  ok: yes\n---\n\nBody\n"
    )
    assert codes(issues) == ["E007", "E008"]
    assert parsed.unknown_keys == ("requires",)
    assert parsed.metadata == {
        "ok": "True"
    }  # scalars are stringified, mappings refused


def test_name_rule_matches_spec_and_directory():
    assert (
        fm.validate_name("") and fm.validate_name("Report") and fm.validate_name("a--b")
    )
    assert fm.validate_name("-a") and fm.validate_name("a" * 65)
    assert fm.validate_name("café-tool") == []  # unicode lowercase is allowed
    assert fm.validate_name("report", directory_name="other")[0].code == "E003"


def test_missing_frontmatter_is_e002():
    parsed, issues = fm.parse("# just markdown\n")
    assert parsed is None and codes(issues) == ["E002"]


def test_validate_bundle_reference_suggestion_and_scripts():
    bundle = Bundle(
        {
            "SKILL.md": skill_md(
                "greeting",
                "Tell the time in the user's timezone. Use when asked what time it is.",
                body="Run `python new-script.py` and see docs/missing.md.\n",
            ),
            "scripts/new-script.py": b"import datetime\nopen('../secret')\n",
        }
    )
    report = validate_bundle(bundle, directory_name="greeting")
    w001 = [i for i in report.issues if i.code == "W001"]
    assert [i.suggestion for i in w001] == ["scripts/new-script.py", None]
    assert "docs/missing.md" in w001[1].message
    assert any(
        i.code == "W002" and i.path == "scripts/new-script.py" for i in report.issues
    )
    assert report.ok  # warnings only


def test_validate_bundle_errors():
    bundle = Bundle(
        {
            "SKILL.md": skill_md("Bad Name", "short", body=""),
            "../escape.py": b"",
            "SKILL.md/inner": b"",
        }
    )
    report = validate_bundle(bundle, directory_name="bad-name")
    assert not report.ok
    assert {"E003", "E004", "E005", "W004"} <= set(codes(report.issues))


def test_validate_without_directory_skips_the_match_rule():
    bundle = Bundle(
        {
            "SKILL.md": skill_md(
                "any-name", "A skill written in an app, no folder. Use whenever."
            )
        }
    )
    assert validate_bundle(bundle).ok


def test_missing_skill_md_and_duplicates():
    assert validate_bundle(Bundle({"x": b""})).errors[0].code == "E001"
    assert [i.code for i in duplicate_name_issues(["a", "b", "a"])] == ["W003"]
