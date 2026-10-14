from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langgraph.types import Overwrite
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.exceptions import AlreadyExistsError, DomainValidationError
from app.main import app
from app.runtime.api.costs import _SERDE, CostService
from app.runtime.costs.models import CostBackfillDB, ThreadCostDB
from app.runtime.costs.schemas import BackfillRequest
from app.runtime.costs.service import analytics, count_threads, enqueue, read_summary
from app.runtime.costs.worker import CostBackfillWorker, CostSettings
from app.runtime.runs.models import RunDB
from app.threads.dependencies import authorize_thread_read
from app.threads.models import ThreadDB
from tests.runtime.test_costs import call, model


START = datetime(2026, 10, 5, tzinfo=UTC)
END = START + timedelta(days=7)
OWNER = uuid4()


@pytest.fixture
async def cost_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'costs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    ThreadDB.__table__,
                    RunDB.__table__,
                    ThreadCostDB.__table__,
                    CostBackfillDB.__table__,
                ],
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE checkpoint_writes (thread_id TEXT, checkpoint_id TEXT, checkpoint_ns TEXT, task_id TEXT, idx INTEGER, channel TEXT, type TEXT, blob BLOB)"
            )
        )
        await connection.execute(text("CREATE TABLE checkpoints (thread_id TEXT)"))
    async with AsyncSession(engine) as db:
        db.add(CostBackfillDB())
        await db.commit()
    monkeypatch.setattr("app.runtime.costs.worker.engine", engine)
    monkeypatch.setattr(
        "app.runtime.costs.worker.cost_settings",
        CostSettings(thread_pause_seconds=0.01, chunk_pause_seconds=0.01),
    )
    monkeypatch.setattr(
        "app.runtime.costs.service.get_whitelist", AsyncMock(return_value=[model()])
    )
    monkeypatch.setattr(
        "app.runtime.api.costs.get_whitelist", AsyncMock(return_value=[model()])
    )
    yield engine
    await engine.dispose()


async def add_thread(engine, id, created_at=START, owner=OWNER, *, messages=None):
    async with AsyncSession(engine) as db:
        db.add(
            ThreadDB(
                id=id,
                model_id="test-model",
                user_id=owner,
                agent_id=uuid4(),
                created_at=created_at,
                updated_at=created_at,
            )
        )
        for i, message in enumerate(messages if messages is not None else [call()]):
            type_tag, blob = _SERDE.dumps_typed(message)
            await db.execute(
                text(
                    "INSERT INTO checkpoint_writes VALUES (:thread, :checkpoint, :namespace, :task, 0, 'messages', :type, :blob)"
                ),
                {
                    "thread": id,
                    "checkpoint": str(i),
                    "namespace": "tools:child" if i else "",
                    "task": str(i),
                    "type": type_tag,
                    "blob": blob,
                },
            )
        await db.commit()


async def queue(engine, start=START, end=END):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        result = await enqueue(db, BackfillRequest(start_at=start, end_at=end))
        await db.commit()
        return result


async def test_backfill_uses_one_connection_and_one_summary_per_thread(cost_db):
    await add_thread(
        cost_db, "included", messages=[call(), Overwrite(value=[call()]), call("child")]
    )
    await add_thread(cost_db, "before", START - timedelta(seconds=1))
    await add_thread(cost_db, "end", END)
    await queue(cost_db)
    checkouts = []
    event.listen(cost_db.sync_engine, "checkout", lambda *args: checkouts.append(1))
    await CostBackfillWorker().tick()
    assert len(checkouts) == 1
    async with AsyncSession(cost_db) as db:
        rows = (await db.execute(select(ThreadCostDB))).scalars().all()
        assert len(rows) == 1 and rows[0].thread_id == "included"
        assert rows[0].total_cost == Decimal("0.0044")
        assert rows[0].summary["call_count"] == 2
        assert "messages" not in rows[0].summary
        assert "message_id" not in str(rows[0].summary)
        job = await db.get(CostBackfillDB, 1)
        assert job.status == "complete" and job.processed == 1
        # The denominator is fixed at queue time, with the same range rules.
        assert job.total == 1 and job.finished_at is not None
        assert job.new_cost == Decimal("0.0044") and job.previous_cost == 0


async def test_missing_prices_can_be_backfilled_without_growing_tables(
    cost_db, monkeypatch
):
    await add_thread(cost_db, "thread")
    monkeypatch.setattr(
        "app.runtime.costs.service.get_whitelist",
        AsyncMock(return_value=[model().model_copy(update={"prices": None})]),
    )
    await queue(cost_db)
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        row = await db.get(ThreadCostDB, "thread")
        assert row.total_cost is None and row.known_cost == 0 and not row.complete
        job = await db.get(CostBackfillDB, 1)
        assert job.unpriced_models == ["test-model"] and job.incomplete == 1
    priced = model()
    priced.prices.output *= 2
    monkeypatch.setattr(
        "app.runtime.costs.service.get_whitelist", AsyncMock(return_value=[priced])
    )
    await queue(cost_db)
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        row = await db.get(ThreadCostDB, "thread")
        assert row.complete and row.total_cost == Decimal("0.0030")
        job = await db.get(CostBackfillDB, 1)
        assert job.unpriced_models == [] and job.new_cost == Decimal("0.0030")
        assert await db.scalar(select(func.count()).select_from(ThreadCostDB)) == 1
        assert await db.scalar(select(func.count()).select_from(CostBackfillDB)) == 1


async def test_price_snapshot_survives_catalog_changes_and_interrupted_job(
    cost_db, monkeypatch
):
    await add_thread(cost_db, "one")
    await add_thread(cost_db, "two")
    await queue(cost_db)

    class Interrupted(CostBackfillWorker):
        async def pause(self):
            raise RuntimeError("process interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        await Interrupted().tick()
    expensive = model()
    expensive.prices.input *= 100
    monkeypatch.setattr(
        "app.runtime.costs.service.get_whitelist", AsyncMock(return_value=[expensive])
    )
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        rows = (await db.execute(select(ThreadCostDB))).scalars().all()
        assert len(rows) == 2
        assert all(row.total_cost == Decimal("0.0022") for row in rows)
        assert (await db.get(CostBackfillDB, 1)).processed == 2
        assert (await read_summary(db, await db.get(ThreadDB, "one"))).stale


async def test_active_threads_skipped_and_corrupt_history_does_not_store_zero(cost_db):
    await add_thread(cost_db, "busy")
    await add_thread(cost_db, "missing", messages=[])
    async with AsyncSession(cost_db) as db:
        db.add(RunDB(thread_id="busy", user_id=OWNER, status="running"))
        await db.execute(text("INSERT INTO checkpoints VALUES ('missing')"))
        await db.commit()
    await queue(cost_db)
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        job = await db.get(CostBackfillDB, 1)
        assert job.skipped == 1 and job.failed == 1 and job.processed == 0
        assert await db.scalar(select(func.count()).select_from(ThreadCostDB)) == 0


async def test_cancel_is_seen_between_threads_and_overlaps_rejected(cost_db):
    await add_thread(cost_db, "thread")
    await queue(cost_db)
    async with AsyncSession(cost_db) as db:
        with pytest.raises(AlreadyExistsError):
            await enqueue(db, BackfillRequest())
        job = await db.get(CostBackfillDB, 1)
        job.status = "cancelled"
        await db.commit()
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        assert await db.scalar(select(func.count()).select_from(ThreadCostDB)) == 0


async def test_personal_analytics_are_scoped_and_mark_uncomputed_or_stale(
    cost_db, monkeypatch
):
    await add_thread(cost_db, "mine")
    await add_thread(cost_db, "other", owner=uuid4())
    await add_thread(cost_db, "outside", END)
    await queue(cost_db)
    await CostBackfillWorker().tick()
    async with AsyncSession(cost_db) as db:
        db.add(RunDB(thread_id="outside", user_id=OWNER, status="running"))
        await db.commit()
        report = await analytics(db, OWNER, BackfillRequest(start_at=START, end_at=END))
        assert report.threads == 1 and report.calculated_threads == 1
        assert report.total_cost == Decimal("0.0022")
        assert report.stale_threads == 0
        unknown = await analytics(db, OWNER, BackfillRequest())
        assert unknown.threads == 2 and unknown.total_cost is None
        assert unknown.stale_threads == 0  # no saved estimate to mark stale
        changed = model()
        changed.prices.input *= 2
        monkeypatch.setattr(
            "app.runtime.costs.service.get_whitelist", AsyncMock(return_value=[changed])
        )
        stale = await analytics(db, OWNER, BackfillRequest(start_at=START, end_at=END))
        assert stale.stale_threads == 1 and stale.total_cost is None


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_backfill_is_admin_only(client, current_user, method):
    response = getattr(client, method)(
        "/thread-costs/backfill", **({"json": {}} if method == "post" else {})
    )
    assert response.status_code == 403


def test_backfill_count_is_admin_only(client, current_user):
    assert client.get("/thread-costs/backfill/count").status_code == 403


async def test_count_matches_the_backfill_range(cost_db):
    await add_thread(cost_db, "included")
    await add_thread(cost_db, "before", START - timedelta(seconds=1))
    await add_thread(cost_db, "end", END)
    async with AsyncSession(cost_db) as db:
        now = datetime.now(UTC)
        ranged = await count_threads(
            db, BackfillRequest(start_at=START, end_at=END), now
        )
        assert ranged.threads == 1
        everything = await count_threads(db, BackfillRequest(), now)
        assert everything.threads == 3
        assert everything.first_created_at.replace(tzinfo=UTC) == START - timedelta(
            seconds=1
        )


def test_backfill_date_validation(client, admin_user):
    assert (
        client.post(
            "/thread-costs/backfill",
            json={"start_at": END.isoformat(), "end_at": START.isoformat()},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/thread-costs/backfill", json={"start_at": "2026-10-05T00:00:00"}
        ).status_code
        == 422
    )


def test_analytics_rejects_reversed_dates(client, current_user):
    assert (
        client.get(
            "/thread-costs/analytics",
            params={"start_at": END.isoformat(), "end_at": START.isoformat()},
        ).status_code
        == 400
    )


async def test_live_scan_is_read_only_and_closes_cursor(cost_db):
    await add_thread(cost_db, "thread")
    async with AsyncSession(cost_db) as db:
        result = await CostService(db).conversation("thread", "test-model")
        assert result.total_cost == Decimal("0.0022")
        assert await db.scalar(select(func.count()).select_from(ThreadCostDB)) == 0
        assert (
            await CostService(db).message("thread", "test-model", "call-1")
        ).cost_details.total == Decimal("0.0022")
    async with AsyncSession(cost_db) as db:
        await db.execute(text("INSERT INTO checkpoints VALUES ('legacy')"))
        await db.commit()
        with pytest.raises(DomainValidationError):
            await CostService(db).conversation("legacy", "test-model")


def test_summary_has_thread_read_authorization(client, current_user):
    async def denied():
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError("Not allowed")

    app.dependency_overrides[authorize_thread_read] = denied
    assert client.get("/threads/thread/cost/summary").status_code == 403
    assert client.post("/threads/thread/cost/refresh").status_code == 403


async def test_postgres_lock_rejection_does_not_start_another_worker(monkeypatch):
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    connection.scalar = AsyncMock(return_value=False)
    connection.commit = AsyncMock()
    engine = MagicMock()
    engine.connect.return_value.__aenter__.return_value = connection
    monkeypatch.setattr("app.runtime.costs.worker.engine", engine)
    worker = CostBackfillWorker()
    worker.process = AsyncMock()
    await worker.tick()
    engine.connect.assert_called_once()
    worker.process.assert_not_awaited()
    assert "pg_try_advisory_lock" in str(connection.scalar.call_args.args[0])


def test_migration_upgrade_seeds_singleton_and_downgrade_removes_tables():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = (
        Path(__file__).parents[2]
        / "alembic/versions/2c86ef7a1b93_add_thread_cost_summaries.py"
    )
    spec = importlib.util.spec_from_file_location("cost_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE threads (id TEXT PRIMARY KEY, created_at DATETIME)")
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert (
            connection.scalar(
                text("SELECT count(*) FROM cost_backfill WHERE status = 'idle'")
            )
            == 1
        )
        assert "thread_costs" in inspect(connection).get_table_names()
        assert "ix_threads_created_at_id" in {
            index["name"] for index in inspect(connection).get_indexes("threads")
        }
        module.downgrade()
        assert inspect(connection).get_table_names() == ["threads"]
    engine.dispose()
