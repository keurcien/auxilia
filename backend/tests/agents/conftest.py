"""A real (SQLite) database for the agent tables, shared by every `tests/agents`
module.

`get_run_spec`'s whole point is the *number* of round-trips it makes, and a
mocked session can't tell you that — it only tells you what you told it to say.
So these tests run against a real engine with a statement counter attached.
The same goes for the whole-set-replace and bulk-delete paths (P3-5): a mocked
session can only confirm the calls a test already knew to expect, which is why
rewriting one to issue a single `DELETE ... WHERE` broke four tests without
breaking any behaviour.

Two accommodations make the Postgres schema loadable on SQLite:

* `JSONB` gets a SQLite DDL rendering (`JSON`). Only the DDL needs it — the
  bind/result processors JSONB inherits from `types.JSON` already work on any
  dialect, so values round-trip normally.
* Tables are created by walking the foreign-key closure of the ones under test,
  rather than the whole metadata: several unrelated tables carry Postgres-only
  columns, and pulling them in would fail for reasons that have nothing to do
  with agents.

Foreign keys are not enforced by default on SQLite, which is why fixtures can
reference owner/tag ids that were never inserted.
"""

import pytest
from sqlalchemy import Table, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

import app.main  # noqa: F401 — imported for the side effect of registering every model
from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
    AgentSandboxDB,
    AgentSubagentDB,
    AgentTeamDB,
    AgentUserPermissionDB,
)


@compiles(JSONB, "sqlite")
def _render_jsonb_as_json_on_sqlite(type_, compiler, **kw) -> str:
    return "JSON"


def _fk_closure(roots: list[Table]) -> list[Table]:
    """Every table reachable from `roots` by following foreign keys."""
    seen: set[str] = set()
    stack = list(roots)
    out: list[Table] = []
    while stack:
        table = stack.pop()
        if table.name in seen:
            continue
        seen.add(table.name)
        out.append(table)
        stack.extend(fk.column.table for fk in table.foreign_keys)
    return out


AGENT_TABLES = _fk_closure(
    [
        AgentDB.__table__,
        AgentMCPServerDB.__table__,
        AgentSandboxDB.__table__,
        AgentSubagentDB.__table__,
        AgentTeamDB.__table__,
        AgentUserPermissionDB.__table__,
    ]
)


class StatementCounter:
    """Counts SQL statements issued on an engine, so a test can assert that a
    read stays flat as the graph it reads grows."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __len__(self) -> int:
        return len(self.statements)

    def reset(self) -> None:
        self.statements.clear()


@pytest.fixture
async def agent_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}")

    def _create(conn):
        SQLModel.metadata.create_all(conn, tables=AGENT_TABLES)

    async with engine.begin() as conn:
        await conn.run_sync(_create)
    yield engine
    await engine.dispose()


@pytest.fixture
async def agent_session(agent_engine):
    factory = sessionmaker(
        bind=agent_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest.fixture
def statements(agent_engine) -> StatementCounter:
    """Counts statements on `agent_engine`. Call `.reset()` after seeding so the
    count covers only the code under test."""
    counter = StatementCounter()

    @event.listens_for(agent_engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        counter.statements.append(statement)

    return counter
