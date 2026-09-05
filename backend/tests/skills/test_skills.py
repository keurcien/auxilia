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
from app.skills.bundles import export_bundle, import_bundle
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
        title="Invoice check",
        description="Use to reconcile invoices",
        instructions="Read scripts/check.py and check invoices.",
        files=[SkillFile(path="scripts/check.py", content="print('checked')")],
    )


async def test_versions_conflicts_and_private_permissions(db, owner, bundle):
    service = SkillService(db)
    skill = await service.save(SkillSave(bundle=bundle), owner)
    other = UserDB(email="other@skills.test")
    db.add(other)
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.authorize(skill.id, other)
    published = await service.publish(skill.id, skill.revision, owner)
    bundle.instructions = "New procedure"
    changed = await service.save(
        SkillSave(bundle=bundle, revision=published.revision, visibility="workspace"),
        owner,
        skill.id,
    )
    assert changed.versions[0].bundle.instructions != "New procedure"
    with pytest.raises(AlreadyExistsError):
        await service.save(SkillSave(bundle=bundle, revision=1), owner, skill.id)
    with pytest.raises(PermissionDeniedError):
        await service.authorize(skill.id, other, edit=True)
    restored = await service.restore(
        skill.id, published.versions[0].id, changed.revision, owner
    )
    assert restored.draft.instructions == published.versions[0].bundle.instructions


async def test_attachment_authorization_compatibility_and_snapshot(db, owner, bundle):
    service = SkillService(db)
    agent = AgentDB(name="Analyst", owner_id=owner.id, instructions="Help")
    db.add(agent)
    await db.flush()
    skill = await service.save(SkillSave(bundle=bundle), owner)
    skill = await service.publish(skill.id, skill.revision, owner)
    await service.attach(agent.id, skill.id, skill.versions[0].id, owner)
    spec = (await AgentRepository(db).get_run_spec(agent.id)).agent
    frozen = await resolve_skills(db, spec, str(owner.id), "unused")
    bundle.instructions = "Changed"
    changed = await service.save(
        SkillSave(bundle=bundle, revision=skill.revision), owner, skill.id
    )
    changed = await service.publish(skill.id, changed.revision, owner)
    await service.attach(agent.id, skill.id, changed.versions[0].id, owner)
    resumed = await resolve_skills(db, spec, str(owner.id), "unused", frozen)
    assert resumed["entries"][0]["bundle"]["instructions"] != "Changed"
    with pytest.raises(DomainValidationError):
        await service.delete(skill.id, owner)
    bundle.requires_code = True
    changed = await service.save(
        SkillSave(bundle=bundle, revision=changed.revision), owner, skill.id
    )
    changed = await service.publish(skill.id, changed.revision, owner)
    with pytest.raises(DomainValidationError, match="Code execution"):
        await service.attach(agent.id, skill.id, changed.versions[0].id, owner)
    other = UserDB(email="other@skills.test")
    db.add(other)
    await db.flush()
    with pytest.raises(PermissionDeniedError):
        await service.detach(agent.id, skill.id, other)
    await service.detach(agent.id, skill.id, owner)
    assert not await service.repository.bindings(agent_id=agent.id)


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
    assert imported.requires_code


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
    assert "Read scripts/check.py" in read.invoke({"name": bundle.name})
    assert (
        read.invoke({"name": bundle.name, "path": "scripts/check.py"})
        == "print('checked')"
    )
    assert "not in" in read.invoke({"name": "not-authorized"})
    assert (
        sandbox_files(catalog)[1][0]
        == f"/skills/invoice-check/{bundle.digest()}/scripts/check.py"
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
        FileDownloadResponse(path="/skills/test/SKILL.md", content=b"test", error=None)
    ]
    lazy = LazySandboxBackend()
    lazy.skill_files = [("/skills/test/SKILL.md", b"test")]
    backend.upload_files.return_value = []
    with pytest.raises(RuntimeError):
        lazy.connect(backend)
    assert not lazy.connected
    backend.upload_files.return_value = [
        FileUploadResponse(path="/skills/test/SKILL.md", error=None)
    ]
    lazy.connect(backend)
    assert lazy.connected


async def test_run_snapshot_survives_publish_and_resume(db, owner, bundle):
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
    skill = await service.save(SkillSave(bundle=bundle), owner)
    skill = await service.publish(skill.id, skill.revision, owner)
    await service.attach(agent.id, skill.id, skill.versions[0].id, owner)
    first = RunDB(thread_id=thread.id, user_id=owner.id, status=RunStatus.interrupted)
    db.add(first)
    await db.flush()
    snapshot = await prepare_run_skills(db, first, thread)
    bundle.instructions = "Updated instructions"
    skill = await service.save(
        SkillSave(bundle=bundle, revision=skill.revision), owner, skill.id
    )
    skill = await service.publish(skill.id, skill.revision, owner)
    await service.attach(agent.id, skill.id, skill.versions[0].id, owner)
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


async def test_draft_test_is_isolated_from_live_attachment(
    db, owner, bundle, monkeypatch
):
    from app.model_providers.service import ModelService
    from app.skills.schemas import SkillTest

    monkeypatch.setattr(ModelService, "is_available", lambda *a, **k: _available())
    service = SkillService(db)
    agent = AgentDB(name="Analyst", owner_id=owner.id, instructions="Help")
    db.add(agent)
    await db.flush()
    skill = await service.save(SkillSave(bundle=bundle), owner)
    skill = await service.publish(skill.id, skill.revision, owner)
    await service.attach(agent.id, skill.id, skill.versions[0].id, owner)
    bundle.instructions = "Draft only"
    skill = await service.save(
        SkillSave(bundle=bundle, revision=skill.revision), owner, skill.id
    )
    result = await service.test(
        skill.id,
        SkillTest(agent_id=agent.id, model_id="test", prompt="Check invoices"),
        owner,
    )
    spec = (await AgentRepository(db).get_run_spec(agent.id)).agent
    test = await resolve_skills(db, spec, str(owner.id), result["thread"].id)
    live = await resolve_skills(db, spec, str(owner.id), "another-thread")
    assert test["entries"][0]["bundle"]["instructions"] == "Draft only"
    assert live["entries"][0]["bundle"]["instructions"] != "Draft only"


async def _available():
    return True
