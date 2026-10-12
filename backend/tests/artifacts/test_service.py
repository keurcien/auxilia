from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.artifacts.models import ArtifactDB
from app.artifacts.schemas import PresentFile
from app.artifacts.service import ArtifactGoneError, ArtifactService
from app.artifacts.settings import ArtifactSettings
from app.artifacts.storage import ObjectMissingError
from app.exceptions import NotFoundError
from app.sandbox.provider import SandboxGoneError


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'artifacts.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[ArtifactDB.__table__]
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def sandbox():
    return SimpleNamespace(
        id="original-sandbox",
        upload_files=MagicMock(return_value=[SimpleNamespace(error=None)]),
        execute=MagicMock(return_value=SimpleNamespace(exit_code=0)),
    )


async def publish(service, sandbox, call="call-1"):
    return await service.publish(
        thread_id="thread",
        tool_call_id=call,
        file=PresentFile(path="/tmp/report.csv"),
        backend=sandbox,
        sandbox_source_id=uuid4(),
    )


async def test_temporary_publication_is_replay_safe_and_snapshots(
    db, sandbox, monkeypatch
):
    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings", ArtifactSettings(_env_file=None)
    )
    reader = MagicMock(return_value=b"a,b\n1,2")
    monkeypatch.setattr("app.artifacts.service.read_bytes", reader)
    service = ArtifactService(db)
    first = await publish(service, sandbox)
    repeated = await publish(service, sandbox)
    revision = await publish(service, sandbox, "call-2")
    assert first.temporary and first.id == repeated.id and first.id != revision.id
    assert reader.call_count == 2
    assert sandbox.upload_files.call_args.args[0][0][0].startswith(
        "/tmp/.auxilia-artifacts/"
    )
    assert len(await service.list("thread")) == 2
    with pytest.raises(NotFoundError):
        await service.content("other-thread", first.id)


async def test_persisted_content_does_not_reconnect_sandbox(db, sandbox, monkeypatch):
    cfg = ArtifactSettings(_env_file=None, s3_bucket="private")
    monkeypatch.setattr("app.artifacts.service.artifact_settings", cfg)
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"a,b")
    store = MagicMock()
    store.get.return_value = b"a,b"
    monkeypatch.setattr("app.artifacts.service.S3ObjectStore", lambda cfg: store)
    service = ArtifactService(db)
    item = await publish(service, sandbox)
    assert not item.temporary
    sandbox.upload_files.assert_not_called()
    assert (await service.content("thread", item.id))[1] == b"a,b"
    store.get.side_effect = ObjectMissingError
    with pytest.raises(ArtifactGoneError):
        await service.content("thread", item.id)
    store.get.side_effect = ConnectionError
    with pytest.raises(ConnectionError):
        await service.content("thread", item.id)


async def test_upload_failure_does_not_publish_success(db, sandbox, monkeypatch):
    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings",
        ArtifactSettings(_env_file=None, s3_bucket="private"),
    )
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"a,b")
    store = MagicMock()
    store.put.side_effect = ConnectionError("storage offline")
    monkeypatch.setattr("app.artifacts.service.S3ObjectStore", lambda cfg: store)
    service = ArtifactService(db)
    with pytest.raises(ConnectionError):
        await publish(service, sandbox)
    assert await service.list("thread") == []


async def test_expired_original_sandbox_is_not_replaced(db, sandbox, monkeypatch):
    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings", ArtifactSettings(_env_file=None)
    )
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"a,b")
    service = ArtifactService(db)
    item = await publish(service, sandbox)
    monkeypatch.setattr(
        "app.artifacts.service.SandboxRepository.get", AsyncMock(return_value=object())
    )
    provider = MagicMock()
    provider.connect.side_effect = SandboxGoneError()
    monkeypatch.setattr("app.artifacts.service.build_provider", lambda source: provider)
    with pytest.raises(ArtifactGoneError, match="expired"):
        await service.content("thread", item.id)
    provider.connect.assert_called_once_with("original-sandbox")
    provider.create.assert_not_called()


async def test_modified_temporary_snapshot_is_not_returned(db, sandbox, monkeypatch):
    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings", ArtifactSettings(_env_file=None)
    )
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"a,b")
    service = ArtifactService(db)
    item = await publish(service, sandbox)
    monkeypatch.setattr(
        "app.artifacts.service.SandboxRepository.get", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "app.artifacts.service.build_provider",
        lambda source: SimpleNamespace(connect=lambda id: sandbox),
    )
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"changed")
    with pytest.raises(ArtifactGoneError, match="original bytes"):
        await service.content("thread", item.id)


async def test_listing_pages_by_keyset_after_the_last_seen_row(
    db, sandbox, monkeypatch
):
    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings", ArtifactSettings(_env_file=None)
    )
    monkeypatch.setattr(
        "app.artifacts.service.read_bytes", MagicMock(return_value=b"a,b\n1,2")
    )
    service = ArtifactService(db)
    for call in ["call-1", "call-2", "call-3"]:
        await publish(service, sandbox, call)
    everything = await service.list("thread")
    rest = await service.list("thread", after=everything[0].id)
    assert [x.id for x in rest] == [x.id for x in everything[1:]]
    assert await service.list("thread", after=everything[-1].id) == []


async def test_unreachable_sandbox_read_is_a_domain_error(db, sandbox, monkeypatch):
    from app.artifacts.files import SandboxReadError
    from app.exceptions import DomainValidationError

    monkeypatch.setattr(
        "app.artifacts.service.artifact_settings", ArtifactSettings(_env_file=None)
    )
    monkeypatch.setattr(
        "app.artifacts.service.read_bytes",
        MagicMock(side_effect=SandboxReadError("/tmp/report.csv")),
    )
    with pytest.raises(DomainValidationError):
        await publish(ArtifactService(db), sandbox)


async def test_discarded_batch_deletes_its_uploaded_objects(db, sandbox, monkeypatch):
    cfg = ArtifactSettings(_env_file=None, s3_bucket="private")
    monkeypatch.setattr("app.artifacts.service.artifact_settings", cfg)
    monkeypatch.setattr("app.artifacts.service.read_bytes", lambda *args: b"a,b")
    store = MagicMock()
    monkeypatch.setattr("app.artifacts.service.S3ObjectStore", lambda cfg: store)
    service = ArtifactService(db)
    await publish(service, sandbox, "call-1")
    await publish(service, sandbox, "call-2")
    uploaded = [put.args[0] for put in store.put.call_args_list]
    store.delete.side_effect = [ConnectionError, None]  # one failure is tolerated
    await service.discard_uploads()
    assert [d.args[0] for d in store.delete.call_args_list] == uploaded
    assert service.uploaded == []
