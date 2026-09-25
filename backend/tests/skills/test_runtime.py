"""Skills at run time: the frozen set, the in-memory backend, the sandbox
upload, and a sandbox-less agent reading a skill end to end."""

import base64
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.exceptions import DomainValidationError
from app.skills.bundles import parse_skill
from app.skills.middleware import SKILLS_ROOT
from app.skills.runtime import (
    DIGEST_MARKER,
    READ_ONLY,
    SkillsBackend,
    ensure_unique_names,
    resolve_run_skills,
    skill_files,
    upload_skills,
)
from app.skills.schemas import SkillFile
from tests.runtime.test_agent_behaviour import build_agent, collect, system_text
from tests.sandbox.stub_sandbox import StubSandbox
from tests.skills.conftest import (
    attach,
    link_subagent,
    seed_agent,
    seed_skill,
    skill_markdown,
)


REPORT = parse_skill(
    skill_markdown("report", "Write a report"),
    [
        SkillFile(path="scripts/run.py", content="print('hi')\n"),
        SkillFile(
            path="assets/logo.png",
            content=base64.b64encode(b"\x89PNG").decode(),
            encoding="base64",
        ),
    ],
)
TRIAGE = parse_skill(skill_markdown("triage", "Triage a bug"))


# --- the in-memory backend --------------------------------------------------


def test_skill_files_lay_out_one_folder_per_skill_under_the_root():
    files = skill_files([REPORT, TRIAGE])
    assert sorted(files) == [
        f"{SKILLS_ROOT}/report/SKILL.md",
        f"{SKILLS_ROOT}/report/assets/logo.png",
        f"{SKILLS_ROOT}/report/scripts/run.py",
        f"{SKILLS_ROOT}/triage/SKILL.md",
    ]
    assert files[f"{SKILLS_ROOT}/report/assets/logo.png"] == b"\x89PNG"


def test_backend_serves_the_layout_skills_middleware_scans():
    backend = SkillsBackend([REPORT, TRIAGE])

    listing = backend.ls(SKILLS_ROOT)
    assert [e["path"] for e in listing.entries if e["is_dir"]] == [
        f"{SKILLS_ROOT}/report/",
        f"{SKILLS_ROOT}/triage/",
    ]
    [download] = backend.download_files([f"{SKILLS_ROOT}/report/SKILL.md"])
    assert download.content == REPORT.content.encode()
    read = backend.read(f"{SKILLS_ROOT}/report/scripts/run.py")
    assert read.error is None and "print('hi')" in read.file_data["content"]
    assert backend.read(f"{SKILLS_ROOT}/nope").error
    assert backend.glob("*.py").matches[0]["path"].endswith("scripts/run.py")


def test_backend_refuses_every_write_without_raising():
    backend = SkillsBackend([REPORT])
    path = f"{SKILLS_ROOT}/report/SKILL.md"
    assert backend.write(path, "x").error == READ_ONLY
    assert backend.edit(path, "a", "b").error == READ_ONLY
    assert backend.delete(path).error == READ_ONLY
    assert backend.upload_files([(path, b"x")])[0].error == READ_ONLY
    assert backend.read(path).error is None  # untouched


# --- the sandbox upload -----------------------------------------------------


def test_a_failed_file_never_leaves_the_digest_marker_behind():
    """The P2 from review: backends report a failed file and keep uploading
    the rest, so a marker written in the same batch could land while a script
    did not. The next run's digest check would then match and return early,
    leaving the script missing until the bundle itself changed."""
    sandbox = StubSandbox()
    files = skill_files([REPORT])
    script = next(path for path in files if path.endswith("run.py"))
    sandbox.fail_paths = {script}

    with pytest.raises(RuntimeError, match="skill files"):
        upload_skills(sandbox, files)

    # No marker, so the next attempt cannot short-circuit.
    assert f"{SKILLS_ROOT}/{DIGEST_MARKER}" not in sandbox.files

    sandbox.fail_paths = set()
    assert upload_skills(sandbox, files) is True
    assert sandbox.files[script] == files[script]
    assert f"{SKILLS_ROOT}/{DIGEST_MARKER}" in sandbox.files


def test_upload_writes_everything_once_then_reuses_by_digest():
    sandbox = StubSandbox()
    files = skill_files([REPORT])

    assert upload_skills(sandbox, files) is True
    assert set(files) <= set(sandbox.files)
    assert f"{SKILLS_ROOT}/{DIGEST_MARKER}" in sandbox.files
    # Two batches on purpose: the files, then the marker (see below).
    assert len(sandbox.uploads) == 2

    assert upload_skills(sandbox, files) is False  # one `cat`, no upload
    assert len(sandbox.uploads) == 2  # unchanged: nothing was uploaded again


def test_upload_recreates_the_root_when_a_skill_changed():
    sandbox = StubSandbox()
    upload_skills(sandbox, skill_files([REPORT]))
    sandbox.files["/tmp/auxilia-skills/report/scratch.txt"] = b"model wrote this"

    changed = parse_skill(skill_markdown("report", "Write a report"))  # files removed
    assert upload_skills(sandbox, skill_files([changed])) is True

    assert f"{SKILLS_ROOT}/report/scripts/run.py" not in sandbox.files
    assert f"{SKILLS_ROOT}/report/scratch.txt" not in sandbox.files
    assert f"{SKILLS_ROOT}/report/SKILL.md" in sandbox.files


def test_upload_removes_the_root_when_there_are_no_skills():
    sandbox = StubSandbox()
    upload_skills(sandbox, skill_files([REPORT]))
    assert upload_skills(sandbox, {}) is False
    assert not any(p.startswith(SKILLS_ROOT) for p in sandbox.files)


def test_upload_failure_raises_rather_than_half_writing():
    sandbox = StubSandbox()
    sandbox.fail_uploads = True
    with pytest.raises(RuntimeError, match="Failed to upload"):
        upload_skills(sandbox, skill_files([REPORT]))


# --- resolving the run's set ------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_the_graph_union_once_per_skill(agent_session):
    """A supervisor and its subagents run with one skill set: the union of
    what they each have enabled, with a skill on both sides counted once."""
    supervisor = await seed_agent(agent_session)
    subagent = await seed_agent(agent_session)
    await link_subagent(agent_session, supervisor.id, subagent.id)
    shared = await seed_skill(agent_session, owner_id=uuid4(), name="shared")
    await attach(agent_session, supervisor.id, shared.id)
    await attach(agent_session, subagent.id, shared.id)
    await attach(
        agent_session,
        subagent.id,
        (await seed_skill(agent_session, owner_id=uuid4(), name="sub-only")).id,
    )

    bundles = await resolve_run_skills(agent_session, [supervisor.id, subagent.id])

    assert [b.name for b in bundles] == ["shared", "sub-only"]


@pytest.mark.asyncio
async def test_every_run_reads_the_library_including_a_resume(agent_session):
    """Nothing is copied onto the thread, so there is no second code path: a
    resume resolves exactly as a first run does, and a skill enabled or
    disabled meanwhile takes effect."""
    agent = await seed_agent(agent_session)
    assert await resolve_run_skills(agent_session, [agent.id]) == []

    skill = await seed_skill(agent_session, owner_id=uuid4(), name="triage")
    await attach(agent_session, agent.id, skill.id)
    assert [b.name for b in await resolve_run_skills(agent_session, [agent.id])] == [
        "triage"
    ]


def test_a_run_fails_rather_than_silently_drop_a_colliding_skill():
    """The last backstop, and it should be unreachable: the library's unique
    name is what stops two skills of one name existing at all. It stays
    because the run is where a name becomes a *path* — two skills of one name
    would overwrite each other under `SKILLS_ROOT/<name>/` and the model would
    read whichever landed last. If the data ever says otherwise, fail the run
    rather than pick one."""
    pair = [
        parse_skill(skill_markdown("dup")),
        parse_skill(skill_markdown("dup", "A different one")),
    ]
    with pytest.raises(DomainValidationError, match="'dup'"):
        ensure_unique_names(pair)


# --- a sandbox-less agent, end to end ---------------------------------------


@pytest.mark.asyncio
async def test_plain_agent_lists_and_reads_its_skills_from_memory(in_memory_runtime):
    """No sandbox: the prompt lists the skills, the agent gets exactly `ls`
    and `read_file` over the in-memory view, `read_file` returns the SKILL.md,
    and nothing about the files lands in the checkpoint."""
    from app.runtime.checkpoints import get_checkpoint_state

    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call-1",
                "name": "read_file",
                "args": {"file_path": f"{SKILLS_ROOT}/report/SKILL.md", "limit": 1000},
            }
        ],
    )
    agent, model = build_agent(script=[read_call, "done"])
    agent.skills = [REPORT, TRIAGE]

    await collect(agent, "write the report")

    system = system_text(model)
    assert "## Skills" in system
    assert "**report**: Write a report" in system
    assert f"{SKILLS_ROOT}/triage/SKILL.md" in system
    assert "cannot run scripts yourself" in system
    # The index names each skill's files by absolute path, so the model can
    # run a script straight after reading the SKILL.md, without an `ls`.
    assert (
        f"  -> Files: `{SKILLS_ROOT}/report/assets/logo.png`, "
        f"`{SKILLS_ROOT}/report/scripts/run.py`"
    ) in system
    files_line = next(line for line in system.split("\n") if "-> Files:" in line)
    assert "SKILL.md" not in files_line  # the document has its own Read line
    assert "-> Files:" not in system.split("**triage**")[1]  # triage has no files
    assert {t.name for t in model.bound_tools} == {"ls", "read_file"}
    # The tool result the model saw on its second call is the document.
    tool_message = next(m for m in model.calls[1] if m.type == "tool")
    assert "Do it." in tool_message.content
    state = await get_checkpoint_state(in_memory_runtime, "thread-1")
    assert not state.values.get("files")


@pytest.mark.asyncio
async def test_plain_agent_without_skills_gets_no_fragment_and_no_tools(
    in_memory_runtime,
):
    agent, model = build_agent(script=["done"])
    await collect(agent, "hello")
    assert "## Skills" not in system_text(model)
    assert model.bound_tools == []


@pytest.mark.asyncio
async def test_skill_index_is_rebuilt_every_run(in_memory_runtime):
    """deepagents caches the index in checkpointed state for the thread; a
    skill enabled between two turns must still show up on the second."""
    agent, model = build_agent(script=["one", "two"])
    agent.skills = [REPORT]
    await collect(agent, "first")
    assert "triage" not in system_text(model, 0)

    agent.skills = [REPORT, TRIAGE]
    await collect(agent, "second")
    assert "**triage**" in system_text(model, 1)


@pytest.mark.asyncio
async def test_sandbox_agent_gets_skills_uploaded_and_listed(in_memory_runtime):
    from tests.runtime.test_agent_behaviour import build_sandbox_agent

    agent, model, sandbox = build_sandbox_agent(script=["done"], skills=[REPORT])

    await collect(agent, "hello")

    assert f"{SKILLS_ROOT}/report/scripts/run.py" in sandbox.files
    system = system_text(model)
    assert "**report**" in system
    assert "run a script by that path" in system
    assert f"  -> Files: `{SKILLS_ROOT}/report/assets/logo.png`" in system
    # The sandbox agent keeps the whole harness toolset, not the read-only pair.
    assert {"execute", "write_file", "read_file", "ls"} <= {
        t.name for t in model.bound_tools
    }


def test_index_caps_the_files_it_names():
    from deepagents.middleware.skills import _list_skills

    from app.skills.middleware import INDEX_FILES_MAX, skills_index_middleware

    many = parse_skill(
        skill_markdown("many", "Lots of files"),
        [SkillFile(path=f"references/{i:03d}.md", content="x") for i in range(30)],
    )
    middleware = skills_index_middleware(SkillsBackend([many]), sandbox=True)
    skills = _list_skills(SkillsBackend([many]), SKILLS_ROOT)

    text = middleware._format_skills_list(skills)
    files_line = next(line for line in text.split("\n") if "-> Files:" in line)
    assert files_line.count("`") == INDEX_FILES_MAX * 2 + 2  # 20 paths + the ls hint
    assert f"(+{30 - INDEX_FILES_MAX} more, `ls {SKILLS_ROOT}/many`)" in files_line
    assert f"`{SKILLS_ROOT}/many/references/000.md`" in files_line
    assert f"references/{INDEX_FILES_MAX:03d}.md" not in files_line
