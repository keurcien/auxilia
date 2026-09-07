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
    NotFoundError,
    PermissionDeniedError,
)
from app.sandbox.lazy import LazySandboxBackend
from app.skills.bundles import export_bundle, import_bundle, parse_skill, skill_markdown
from app.skills.runtime import catalog_tools, resolve_skills, sandbox_files
from app.skills.schemas import SkillBundle, SkillFile, SkillSave
from app.skills.service import SkillService
from app.users.models import UserDB


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
    with pytest.raises(NotFoundError):
        await service.authorize(skill.id, other)
    bundle.instructions = "New procedure"
    changed = await service.save(
        SkillSave(
            content=skill_markdown(bundle),
            files=bundle.files,
            revision=skill.revision,
            visibility="workspace",
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


def test_plain_agent_reads_without_sandbox(bundle):
    catalog = {
        "entries": [
            {
                "skill_id": str(uuid4()),
                "number": 1,
                "bundle": bundle.model_dump(mode="json"),
            }
        ]
    }
    read = catalog_tools(catalog)[0]
    instructions = read.invoke({"name": bundle.name})
    assert "Read scripts/check.py" in instructions
    assert f"/tmp/auxilia-skills/{bundle.name}/{bundle.digest()}" in instructions
    assert (
        read.invoke({"name": bundle.name, "path": "scripts/check.py"})
        == "print('checked')"
    )
    assert "not in" in read.invoke({"name": "not-authorized"})
    assert (
        sandbox_files(catalog)[1][0]
        == f"/tmp/auxilia-skills/invoice-check/{bundle.digest()}/scripts/check.py"
    )


def test_sandbox_uploads_before_connect_and_rejects_partial(mocker):
    from deepagents.backends.protocol import (
        ExecuteResponse,
        FileDownloadResponse,
        FileUploadResponse,
    )

    backend = mocker.Mock()
    backend.execute.return_value = ExecuteResponse(output="", exit_code=0)
    backend.download_files.return_value = [
        FileDownloadResponse(
            path="/tmp/auxilia-skills/test/SKILL.md", content=b"test", error=None
        )
    ]
    lazy = LazySandboxBackend()
    lazy.skill_files = [("/tmp/auxilia-skills/test/SKILL.md", b"test")]
    backend.upload_files.return_value = []
    with pytest.raises(RuntimeError):
        lazy.connect(backend)
    assert not lazy.connected
    backend.upload_files.return_value = [
        FileUploadResponse(path="/tmp/auxilia-skills/test/SKILL.md", error=None)
    ]
    lazy.connect(backend)
    assert lazy.connected


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


def test_sandbox_directory_failure_preserves_diagnostic(mocker):
    from deepagents.backends.protocol import ExecuteResponse

    backend = mocker.Mock()
    backend.execute.return_value = ExecuteResponse(
        output="mkdir: cannot create directory: Permission denied", exit_code=1
    )
    lazy = LazySandboxBackend()
    lazy.skill_files = [("/tmp/auxilia-skills/test/SKILL.md", b"test")]
    with pytest.raises(RuntimeError, match=r"exit code 1.*Permission denied"):
        lazy.connect(backend)
    assert not lazy.connected
    backend.upload_files.assert_not_called()


def test_skill_materialization_uses_writable_temporary_storage(bundle, mocker):
    """Simulate a non-root sandbox which rejects root-level directories."""
    import shlex

    from deepagents.backends.protocol import (
        ExecuteResponse,
        FileDownloadResponse,
        FileUploadResponse,
    )

    catalog = {"entries": [{"bundle": bundle.model_dump(mode="json")}]}
    files = sandbox_files(catalog)
    backend = mocker.Mock()

    def execute(command):
        directories = shlex.split(command)[2:]
        writable = all(path.startswith("/tmp/auxilia-skills/") for path in directories)
        return ExecuteResponse(
            output="" if writable else "Permission denied",
            exit_code=0 if writable else 1,
        )

    backend.execute.side_effect = execute
    backend.upload_files.return_value = [
        FileUploadResponse(path=path, error=None) for path, _ in files
    ]
    backend.download_files.return_value = [
        FileDownloadResponse(path=path, content=content, error=None)
        for path, content in files
    ]
    lazy = LazySandboxBackend()
    lazy.skill_files = files
    lazy.connect(backend)
    assert lazy.connected
    backend.upload_files.assert_called_once_with(files)


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
