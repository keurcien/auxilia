from unittest.mock import AsyncMock

import pytest
from fakeredis import FakeServer, aioredis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

import app.agents.runs.service as service_mod
from app.agents.runs.models import RunDB
from app.threads.models import ThreadDB


@pytest.fixture
async def redis():
    """A fresh in-memory async Redis per test (streams + Lua supported).

    An explicit shared `FakeServer` makes every pooled connection see the same
    data — without it, a blocking pop holds one connection and concurrent
    reads land on a different, empty fake server.
    """
    client = aioredis.FakeRedis(server=FakeServer(), decode_responses=True)
    await client.flushall()
    yield client
    await client.aclose()


@pytest.fixture
async def run_db(tmp_path, monkeypatch):
    """A real (SQLite) database behind `RunService`'s short sessions.

    File-based rather than :memory: so every session sees the same data, and
    only the runs/threads tables are created — the other models carry
    Postgres-only column types. FKs are unenforced on SQLite, so the dangling
    user/agent references in fixtures are harmless.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")

    def _create(conn):
        SQLModel.metadata.create_all(conn, tables=[ThreadDB.__table__, RunDB.__table__])

    async with engine.begin() as conn:
        await conn.run_sync(_create)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_mod, "AsyncSessionLocal", factory)
    # These tests exercise the run lifecycle, not the model-availability gate
    # (covered in tests/model_providers/); most fixtures reference threads
    # that don't exist, so stub the gate out.
    monkeypatch.setattr(service_mod.RunService, "_ensure_runnable_thread", AsyncMock())
    yield factory
    await engine.dispose()
