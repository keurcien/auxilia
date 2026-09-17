import ast
import subprocess
import sys
from pathlib import Path

from skillkit.adapters.deepagents import InMemorySkillsBackend, skill_files


PACKAGE = Path(__file__).resolve().parents[2] / "skillkit"
FORBIDDEN = (
    "app",
    "deepagents",
    "langchain",
    "langgraph",
    "sqlalchemy",
    "sqlmodel",
    "fastapi",
)


def test_core_imports_nothing_from_the_app_or_the_agent_stack():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in FORBIDDEN or root.startswith("langchain"):
                    offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
    assert offenders == []


def test_adapter_flattens_to_one_folder_per_skill_and_is_read_only():
    files = skill_files(
        {"a": {"SKILL.md": b"x", "scripts/r.py": b"y"}, "b": {"SKILL.md": b"z"}},
        "/tmp/root",
    )
    assert sorted(files) == [
        "/tmp/root/a/SKILL.md",
        "/tmp/root/a/scripts/r.py",
        "/tmp/root/b/SKILL.md",
    ]
    backend = InMemorySkillsBackend({**files, "/tmp/root/a/assets/bin": b"\xff\xfe"})
    assert backend.write("/tmp/root/a/SKILL.md", "no").error
    [download] = backend.download_files(["/tmp/root/a/SKILL.md"])
    assert download.content == b"x"
    assert {i["path"] for i in backend.glob("*", path="/tmp/root/a").matches} == {
        "/tmp/root/a/SKILL.md",
        "/tmp/root/a/scripts/r.py",
        "/tmp/root/a/assets/bin",
    }


def test_cli_validate_and_lock(tmp_path):
    repo = tmp_path / "repo"
    skill = repo / "skills" / "greeting"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: greeting\ndescription: Tell the time in UTC. Use when asked what time it is.\n---\n\nRun `python new-script.py`.\n"
    )
    (skill / "scripts").mkdir()
    (skill / "scripts" / "new-script.py").write_text("print('hi')\n")

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "skillkit", *args],
            capture_output=True,
            text=True,
            cwd=PACKAGE.parent,
        )

    out = run("validate", str(repo))
    assert (
        out.returncode == 0
        and "W001" in out.stdout
        and "did you mean 'scripts/new-script.py'" in out.stdout
    )
    assert run("validate", str(repo), "--strict").returncode == 1
    lock = tmp_path / "skills.lock"
    assert run("lock", str(repo), "--lock", str(lock)).returncode == 0 and lock.exists()
    assert run("diff", str(repo), "--lock", str(lock)).stdout.startswith(
        "revision unchanged"
    )
    assert run("list", str(repo)).stdout.splitlines()[1].startswith("  greeting")
