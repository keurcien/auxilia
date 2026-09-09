import io
import zipfile
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.agents.core.repository import AgentRepository
from app.agents.models import AgentDB
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    PermissionDeniedError,
)
from app.skills.bundles import export_bundle, import_bundle, parse_skill, skill_markdown
from app.skills.runtime import (
    DIGEST_MARKER,
    materialize_skills,
    resolve_skills,
    skill_files,
    skills_digest,
    skills_root,
    skills_sources,
)
from app.skills.schemas import SkillBundle, SkillFile, SkillSave
from app.skills.service import SkillService
from app.users.models import UserDB
from tests.sandbox.stub_sandbox import StubSandbox


@compiles(JSONB, "sqlite")
def compile_jsonb(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def owner(db):
    user = UserDB(email="owner@skills.test")
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
def bundle():
    return SkillBundle(
        name="invoice-check",
        description="Use to reconcile invoices",
        instructions="Read scripts/check.py and check invoices.",
        files=[SkillFile(path="scripts/check.py", content="print('checked')")],
    )


async def test_save_permissions_and_conflicts(db, owner, bundle):
    service = SkillService(db)
    skill = await service.save(
        SkillSave(content=skill_markdown(bundle), files=bundle.files), owner
    )
    other = UserDB(email="other@skills.test")
    db.add(other)
    await db.flush()
    # Every skill is readable by the whole workspace; only edits are gated.
    assert (await service.authorize(skill.id, other)).id == skill.id
    bundle.instructions = "New procedure"
    changed = await service.save(
        SkillSave(
            content=skill_markdown(bundle),
            files=bundle.files,
            revision=skill.revision,
        ),
        owner,
        skill.id,
    )
    assert "New procedure" in changed.content
    with pytest.raises(AlreadyExistsError):
        await service.save(
            SkillSave(content=skill_markdown(bundle), revision=1), owner, skill.id
        )
    with pytest.raises(PermissionDeniedError):
        await service.authorize(skill.id, other, edit=True)
    assert (await service.authorize(skill.id, other)).id == skill.id


async def test_attachment_uses_saved_content_without_publish(db, owner, bundle):
    service = SkillService(db)
    agent = AgentDB(name="Analyst", owner_id=owner.id, instructions="Help")
    db.add(agent)
    await db.flush()
    skill = await service.save(
        SkillSave(content=skill_markdown(bundle), files=bundle.files), owner
    )
    await service.attach(agent.id, skill.id, owner)
    await service.attach(agent.id, skill.id, owner)  # Idempotent checkbox updates.
    spec = (await AgentRepository(db).get_run_spec(agent.id)).agent
    frozen = await resolve_skills(db, spec, str(owner.id), "unused")
    bundle.instructions = "Changed"
    await service.save(
        SkillSave(
            content=skill_markdown(bundle), files=bundle.files, revision=skill.revision
        ),
        owner,
        skill.id,
    )
    current = await resolve_skills(db, spec, str(owner.id), "unused")
    assert current["entries"][0]["bundle"]["instructions"] == "Changed"
    resumed = await resolve_skills(db, spec, str(owner.id), "unused", frozen)
    assert resumed["entries"][0]["bundle"]["instructions"] != "Changed"
    with pytest.raises(DomainValidationError):
        await service.delete(skill.id, owner)
    other = UserDB(email="other@skills.test")
    db.add(other)
    await db.flush()
    with pytest.raises(PermissionDeniedError):
        await service.detach(agent.id, skill.id, other)
    await service.detach(agent.id, skill.id, owner)
    assert not await service.repository.bindings(agent_id=agent.id)
    await service.delete(skill.id, owner)


@pytest.mark.parametrize(
    "path", ["../secret", "/secret", "foo/../bar", "foo//bar", "SKILL.md", "foo\\bar"]
)
def test_invalid_paths(path):
    with pytest.raises(ValidationError):
        SkillFile(path=path, content="bad")


def test_bundle_roundtrip_binary_and_paths(bundle):
    bundle.files.append(
        SkillFile(path="assets/logo.bin", content="AP8=", encoding="base64")
    )
    imported = import_bundle(export_bundle(bundle), "skill.zip")
    assert imported.name == bundle.name
    assert imported.instructions == bundle.instructions
    assert imported.files[1].bytes() == b"\x00\xff"


def test_archive_traversal():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../../secret", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        import_bundle(stream.getvalue(), "skill.zip")


def test_duplicate_and_invalid_base64(bundle):
    with pytest.raises(ValidationError):
        SkillBundle.model_validate(
            {
                **bundle.model_dump(),
                "files": [
                    {"path": "a", "content": "x"},
                    {"path": "a/b", "content": "y"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        SkillBundle.model_validate(
            {
                **bundle.model_dump(),
                "files": [{"path": "a", "content": "!!!", "encoding": "base64"}],
            }
        )


def test_skill_files_follow_the_layout_the_middleware_scans(bundle):
    """`<root>/<skill-name>/SKILL.md` plus the bundle's files: what
    deepagents' `SkillsMiddleware` lists from a source directory."""
    catalog = {
        "entries": [
            {"skill_id": str(uuid4()), "bundle": bundle.model_dump(mode="json")}
        ]
    }
    root = skills_root("agent-1")

    files = dict(skill_files(catalog, root))

    assert root == "/tmp/auxilia-skills/agent-1"
    assert set(files) == {
        f"{root}/invoice-check/SKILL.md",
        f"{root}/invoice-check/scripts/check.py",
    }
    assert files[f"{root}/invoice-check/scripts/check.py"] == b"print('checked')"
    assert b"name: invoice-check" in files[f"{root}/invoice-check/SKILL.md"]
    assert skills_sources("agent-1", catalog) == [(root, "Agent")]
    assert skills_sources("agent-1", {"entries": []}) is None


def test_materialize_recreates_the_root_and_uploads_everything(bundle):
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    root = skills_root("agent-1")
    files = skill_files(catalog, root)
    backend = StubSandbox()

    assert materialize_skills(backend, root, files) is True

    probe, command = backend.commands
    assert probe.startswith(f"cat {root}/{DIGEST_MARKER}")
    assert command.startswith(f"rm -rf {root} && mkdir -p ")
    assert f"{root}/invoice-check/scripts" in command
    assert backend.files == {
        **dict(files),
        f"{root}/{DIGEST_MARKER}": skills_digest(files).encode(),
    }


def test_materialize_skips_a_sandbox_that_already_has_these_skills(bundle):
    """Reconnecting to the thread's sandbox: the marker matches, so nothing is
    re-uploaded — one `cat` is the whole cost."""
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    root = skills_root("agent-1")
    files = skill_files(catalog, root)
    backend = StubSandbox()
    backend.outputs["cat "] = skills_digest(files) + "\n"

    assert materialize_skills(backend, root, files) is False

    assert len(backend.commands) == 1
    assert backend.files == {}


def test_materialize_reuploads_when_a_skill_changed(bundle):
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    root = skills_root("agent-1")
    stale = skills_digest(skill_files(catalog, root))
    bundle.instructions = "Updated procedure"
    files = skill_files({"entries": [{"bundle": bundle.model_dump(mode="json")}]}, root)
    backend = StubSandbox()
    backend.outputs["cat "] = stale + "\n"

    assert materialize_skills(backend, root, files) is True
    assert backend.files[f"{root}/{DIGEST_MARKER}"] == skills_digest(files).encode()


def test_materialize_clears_the_root_when_all_skills_were_detached():
    backend = StubSandbox()
    backend.files = {"/tmp/auxilia-skills/agent-1/old/SKILL.md": b"x"}

    assert materialize_skills(backend, skills_root("agent-1"), []) is False
    assert backend.commands == ["rm -rf /tmp/auxilia-skills/agent-1"]


def test_materialize_fails_the_run_on_a_partial_upload(bundle):
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    root = skills_root("agent-1")
    files = skill_files(catalog, root)
    backend = StubSandbox()
    backend.fail_uploads.add(f"{root}/invoice-check/scripts/check.py")

    with pytest.raises(RuntimeError, match=r"scripts/check\.py"):
        materialize_skills(backend, root, files)


def test_materialize_preserves_the_directory_diagnostic(bundle):
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    root = skills_root("agent-1")
    backend = StubSandbox(exit_code=1)

    with pytest.raises(RuntimeError, match=r"exit code 1.*Permission denied"):
        materialize_skills(backend, root, skill_files(catalog, root))
    assert backend.files == {}


def test_skill_files_middleware_diffs_against_the_threads_state(bundle):
    """Sandbox-less agents keep their skills in graph state: unchanged files are
    not rewritten, changed ones are, and a path under the agent's root that no
    longer belongs to a skill is deleted (`None` in the files reducer).
    Files outside the root — the agent's own — are left alone."""
    from app.skills.middleware import SkillFilesMiddleware

    root = skills_root("agent-1")
    files = skill_files({"entries": [{"bundle": bundle.model_dump(mode="json")}]}, root)
    middleware = SkillFilesMiddleware(root, files)

    fresh = middleware.before_agent({"files": {}}, None, {})
    assert set(fresh["files"]) == {path for path, _ in files}
    assert fresh["files"][f"{root}/invoice-check/SKILL.md"]["encoding"] == "utf-8"

    settled = {**fresh["files"], "/notes.md": {"content": "mine", "encoding": "utf-8"}}
    assert middleware.before_agent({"files": settled}, None, {}) is None

    bundle.instructions = "Updated"
    changed = SkillFilesMiddleware(
        root,
        skill_files({"entries": [{"bundle": bundle.model_dump(mode="json")}]}, root),
    )
    update = changed.before_agent({"files": settled}, None, {})
    assert set(update["files"]) == {f"{root}/invoice-check/SKILL.md"}

    detached = SkillFilesMiddleware(root, [])
    update = detached.before_agent({"files": settled}, None, {})
    assert update["files"] == {path: None for path, _ in files}


def test_plain_agent_reads_skills_from_state_end_to_end(bundle):
    """The whole sandbox-less path on a real graph: files land in state before
    the index is built, the prompt lists the skill with its path, the model is
    offered only `ls` and `read_file`, and a later run drops a detached skill."""
    from langchain_core.messages import HumanMessage

    from app.agents.runtime import build_runnable
    from tests.agents.scripted_model import ScriptedChatModel

    root = skills_root("agent-1")
    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    model = ScriptedChatModel(script=["ok"])
    graph = build_runnable(
        model=model,
        tools=[],
        system_prompt="You are a test agent",
        skills=skills_sources("agent-1", catalog),
        skill_files=skill_files(catalog, root),
    )

    state = graph.invoke({"messages": [HumanMessage("hi")]})

    system = _prompt_text(model.calls[0][0].content)
    assert "invoice-check" in system
    assert f"{root}/invoice-check/SKILL.md" in system
    assert "Use to reconcile invoices" in system
    assert sorted(t.name for t in model.bound_tools) == ["ls", "read_file"]
    assert set(state["files"]) == {path for path, _ in skill_files(catalog, root)}
    # No code execution here: the prompt says to delegate scripts by path.
    assert "delegate the run" in system
    assert "run scripts by their absolute path" not in system

    # Next run, skill detached: the files are removed from state.
    model = ScriptedChatModel(script=["ok"])
    graph = build_runnable(
        model=model,
        tools=[],
        system_prompt="You are a test agent",
        skills=[(root, "Agent")],
        skill_files=[],
    )
    state = graph.invoke({"messages": [HumanMessage("hi")], "files": state["files"]})
    assert state["files"] == {}
    assert "invoice-check" not in _prompt_text(model.calls[0][0].content)


def _prompt_text(content) -> str:
    """A system message's text, whether it came as a string or text blocks."""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    )


async def test_run_snapshot_survives_save_and_resume(db, owner, bundle):
    from app.agents.runs.models import RunDB
    from app.agents.runs.state import RunStatus
    from app.skills.snapshots import prepare_run_skills
    from app.threads.models import ThreadDB

    service = SkillService(db)
    agent = AgentDB(name="Analyst", owner_id=owner.id, instructions="Help")
    db.add(agent)
    await db.flush()
    thread = ThreadDB(agent_id=agent.id, user_id=owner.id)
    db.add(thread)
    await db.flush()
    skill = await service.save(
        SkillSave(content=skill_markdown(bundle), files=bundle.files), owner
    )
    await service.attach(agent.id, skill.id, owner)
    first = RunDB(thread_id=thread.id, user_id=owner.id, status=RunStatus.interrupted)
    db.add(first)
    await db.flush()
    snapshot = await prepare_run_skills(db, first, thread)
    bundle.instructions = "Updated instructions"
    skill = await service.save(
        SkillSave(
            content=skill_markdown(bundle), files=bundle.files, revision=skill.revision
        ),
        owner,
        skill.id,
    )
    await service.attach(agent.id, skill.id, owner)
    resume = RunDB(thread_id=thread.id, user_id=owner.id, command={"resume": True})
    db.add(resume)
    await db.flush()
    assert await prepare_run_skills(db, resume, thread) == snapshot
    fresh = RunDB(thread_id=thread.id, user_id=owner.id, input={"messages": []})
    db.add(fresh)
    await db.flush()
    latest = await prepare_run_skills(db, fresh, thread)
    assert (
        latest[str(agent.id)]["entries"][0]["bundle"]["instructions"]
        == "Updated instructions"
    )


def test_yaml_source_roundtrips_exactly():
    content = "---\n# Keep my comment\nname: greeting\ndescription: 'Say hello'\ncustom: preserved\n---\n\nSay hello.\n"
    bundle = parse_skill(content, [])
    assert skill_markdown(import_bundle(export_bundle(bundle), "skill.zip")) == content


@pytest.mark.parametrize(
    "content",
    [
        "no frontmatter",
        "---\n- bad\n---\nBody",
        "---\nname: Bad Name\ndescription: hello\n---\nBody",
    ],
)
def test_invalid_yaml(content):
    with pytest.raises(ValueError):
        parse_skill(content, [])
