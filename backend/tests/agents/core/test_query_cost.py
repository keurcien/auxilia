"""What the agent read and mutation paths cost, against a real engine.

These are the P3-5 regressions in one place (design review §3.5, §3.6). Every
assertion here is a number a mocked session cannot produce: it can only replay
the calls a test already told it to expect, which is exactly how a `SELECT` that
nobody consumed survived in the mutation paths, and how `instructions` came to
ship on the list endpoint that drops it.

The numbers are upper bounds on work, not a specification of the SQL — if a
change makes one *smaller*, lower it.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import update

from app.agents.core.repository import AgentRepository
from app.agents.core.service import AgentService
from app.agents.models import AgentDB, AgentMCPServerDB, ToolStatus
from app.agents.schemas import AgentListResponse, AgentPatch, AgentResponse


async def _seed(session, *, owner_id, bindings: int = 0, instructions="x" * 4000):
    agent = AgentDB(name="Agent", instructions=instructions, owner_id=owner_id)
    session.add(agent)
    await session.flush()
    for _ in range(bindings):
        session.add(
            AgentMCPServerDB(
                agent_id=agent.id,
                mcp_server_id=uuid4(),
                tools={"search": ToolStatus.always_allow},
            )
        )
    await session.flush()
    return agent


# ---------------------------------------------------------------------------
# the list projection
# ---------------------------------------------------------------------------


async def test_the_list_never_reads_instructions_or_tool_maps(
    agent_session, statements
):
    """The whole point of §3.5: the heavy columns stay in the database rather
    than being fetched, repeated once per MCP binding by the join, and then
    dropped at serialization time."""
    owner = uuid4()
    await _seed(agent_session, owner_id=owner, bindings=3)
    agent_session.expunge_all()
    statements.reset()

    await AgentService(agent_session).list(user_id=owner)

    selects = " ".join(statements.statements)
    assert "agents.instructions" not in selects
    assert "agent_mcp_servers.tools" not in selects


async def test_the_list_returns_the_slim_schema(agent_session):
    owner = uuid4()
    await _seed(agent_session, owner_id=owner, bindings=1)

    rows = await AgentService(agent_session).list(user_id=owner)

    assert len(rows) == 1
    assert type(rows[0]) is AgentListResponse
    assert len(rows[0].mcp_servers) == 1


async def test_the_list_does_not_query_sandbox_bindings(agent_session, statements):
    """`AgentListResponse` has no `sandboxes` field, so the query that fills it
    is pure waste on this path."""
    owner = uuid4()
    await _seed(agent_session, owner_id=owner)
    statements.reset()

    await AgentService(agent_session).list(user_id=owner)

    assert not any("agent_sandboxes" in s for s in statements.statements)


async def test_the_list_cost_does_not_grow_with_the_number_of_agents(
    agent_session, statements
):
    owner = uuid4()
    for _ in range(5):
        await _seed(agent_session, owner_id=owner, bindings=2)
    agent_session.expunge_all()
    statements.reset()

    rows = await AgentService(agent_session).list(user_id=owner)

    assert len(rows) == 5
    assert len(statements) <= 4


async def test_the_detail_read_still_carries_everything(agent_session):
    """The narrowing is the list path only — `get` is what the editor loads."""
    owner = uuid4()
    agent = await _seed(agent_session, owner_id=owner, bindings=1)

    response = await AgentService(agent_session).get(agent.id, user_id=owner)

    assert isinstance(response, AgentResponse)
    assert response.instructions == "x" * 4000
    assert response.mcp_servers[0].tools == {"search": ToolStatus.always_allow}


# ---------------------------------------------------------------------------
# the mutation paths
# ---------------------------------------------------------------------------


async def test_a_one_column_patch_reads_the_agent_row_once(agent_session, statements):
    """It used to read it three times: the permission gate's row, a `get_or_404`
    that fetched a row only `repository.update` looked at, the `refresh` after
    that update, and then the re-read this returns."""
    owner = uuid4()
    agent = await _seed(agent_session, owner_id=owner)
    agent_session.expunge_all()
    statements.reset()

    response = await AgentService(agent_session).update(
        agent.id, AgentPatch(name="Renamed"), user_id=owner
    )

    assert response.name == "Renamed"
    # The gate reads two columns; only the closing re-read pulls the whole row.
    full_reads = [s for s in statements.statements if "agents.instructions" in s]
    assert len(full_reads) == 1
    assert len(statements) <= 6


async def test_archiving_issues_one_update_and_no_select_of_its_own(
    agent_session, statements
):
    owner = uuid4()
    agent = await _seed(agent_session, owner_id=owner)
    agent_session.expunge_all()
    statements.reset()

    await AgentService(agent_session).delete(agent.id, user_id=owner)

    assert len(statements) == 3  # gate, subagent-link delete, the UPDATE
    assert (await AgentRepository(agent_session).get(agent.id)).is_archived is True


async def test_archiving_an_already_archived_agent_touches_nothing(agent_session):
    """Archiving is deliberately repeatable (`delete` passes
    `include_archived=True` so a second call does not 404), so a repeat must not
    bump `updated_at` — which the agents list renders. The ORM path this
    replaced got that for free, because SQLAlchemy does not mark an attribute
    dirty when it is set to the value it already holds; a bulk UPDATE has to say
    it in the `WHERE`. The statement is still sent, and matches no rows.

    `updated_at` is backdated first, on purpose: SQLite's `CURRENT_TIMESTAMP`
    has one-second resolution, so comparing two timestamps taken in the same
    second passes whether or not the second write happened.
    """
    owner = uuid4()
    agent = await _seed(agent_session, owner_id=owner)
    service = AgentService(agent_session)
    repository = AgentRepository(agent_session)
    await service.delete(agent.id, user_id=owner)
    backdated = datetime(2020, 1, 1, tzinfo=UTC)
    await agent_session.execute(
        update(AgentDB).where(AgentDB.id == agent.id).values(updated_at=backdated)
    )
    agent_session.expunge_all()

    await service.delete(agent.id, user_id=owner)
    agent_session.expunge_all()

    # Compared on the year, not the instant: SQLite hands the column back
    # without the tzinfo it was written with, and the point is only that the
    # backdated value survived rather than being overwritten with "now".
    assert (await repository.get(agent.id)).updated_at.year == backdated.year


async def test_restore_returns_the_unarchived_agent(agent_session):
    owner = uuid4()
    agent = await _seed(agent_session, owner_id=owner)
    service = AgentService(agent_session)
    await service.delete(agent.id, user_id=owner)

    response = await service.restore(agent.id, user_id=owner)

    assert response.is_archived is False
