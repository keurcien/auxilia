"""`AgentRepository.get_run_spec` — the narrow run-path read (design review §2.2).

These run against a real engine (see `conftest.py`): the contract being tested is
partly *how many queries it takes*, which a mocked session cannot observe.
"""

from uuid import UUID, uuid4

import pytest

from app.agents.core.repository import AgentRepository
from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
    AgentSandboxDB,
    AgentSubagentDB,
    ToolStatus,
)
from app.sandbox.models import SandboxDB, SandboxProviderType


async def _add_agent(session, name: str, **kwargs) -> AgentDB:
    agent = AgentDB(
        name=name,
        instructions=f"instructions for {name}",
        owner_id=uuid4(),
        **kwargs,
    )
    session.add(agent)
    await session.flush()
    return agent


async def _bind_server(
    session, agent_id: UUID, tools: dict[str, ToolStatus] | None = None
) -> AgentMCPServerDB:
    binding = AgentMCPServerDB(agent_id=agent_id, mcp_server_id=uuid4(), tools=tools)
    session.add(binding)
    await session.flush()
    return binding


async def _bind_subagent(session, supervisor_id: UUID, subagent_id: UUID) -> None:
    session.add(AgentSubagentDB(supervisor_id=supervisor_id, subagent_id=subagent_id))
    await session.flush()


async def _bind_sandbox(
    session, agent_id: UUID, tools: dict[str, ToolStatus] | None = None
) -> SandboxDB:
    sandbox = SandboxDB(
        name="box",
        provider=SandboxProviderType.opensandbox,
        url="https://sandbox.example.com",
    )
    session.add(sandbox)
    await session.flush()
    session.add(AgentSandboxDB(agent_id=agent_id, sandbox_id=sandbox.id, tools=tools))
    await session.flush()
    return sandbox


async def test_returns_none_for_an_unknown_agent(agent_session):
    assert await AgentRepository(agent_session).get_run_spec(uuid4()) is None


async def test_carries_the_agent_fields_the_runtime_actually_uses(agent_session):
    agent = await _add_agent(agent_session, "Parent", description="a parent")

    spec = await AgentRepository(agent_session).get_run_spec(agent.id)

    assert spec is not None
    assert spec.agent.id == agent.id
    assert spec.agent.name == "Parent"
    assert spec.agent.instructions == "instructions for Parent"
    assert spec.agent.description == "a parent"
    assert spec.agent.mcp_servers == []
    assert spec.agent.sandbox is None
    assert spec.subagents == []


async def test_includes_direct_subagents_but_not_their_subagents(agent_session):
    """One level only — `Agent.build` does not recurse, so neither does the read."""
    parent = await _add_agent(agent_session, "Parent")
    child = await _add_agent(agent_session, "Child")
    grandchild = await _add_agent(agent_session, "Grandchild")
    await _bind_subagent(agent_session, parent.id, child.id)
    await _bind_subagent(agent_session, child.id, grandchild.id)

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    assert [s.id for s in spec.subagents] == [child.id]


async def test_subagents_keep_the_order_they_were_bound_in(agent_session):
    parent = await _add_agent(agent_session, "Parent")
    first = await _add_agent(agent_session, "First")
    second = await _add_agent(agent_session, "Second")
    await _bind_subagent(agent_session, parent.id, first.id)
    await _bind_subagent(agent_session, parent.id, second.id)

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    assert [s.name for s in spec.subagents] == ["First", "Second"]


async def test_an_archived_agent_still_resolves(agent_session):
    """A subagent is routinely archived out of the agents list while still wired
    to a supervisor, and a run under way must survive its agent being archived."""
    parent = await _add_agent(agent_session, "Parent", is_archived=True)
    child = await _add_agent(agent_session, "Child", is_archived=True)
    await _bind_subagent(agent_session, parent.id, child.id)

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    assert [s.id for s in spec.subagents] == [child.id]


async def test_bindings_land_on_the_agent_that_owns_them(agent_session):
    parent = await _add_agent(agent_session, "Parent")
    child = await _add_agent(agent_session, "Child")
    await _bind_subagent(agent_session, parent.id, child.id)
    parent_binding = await _bind_server(
        agent_session, parent.id, {"search": ToolStatus.needs_approval}
    )
    child_binding = await _bind_server(agent_session, child.id, None)

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    assert [b.id for b in spec.agent.mcp_servers] == [parent_binding.id]
    assert spec.agent.mcp_servers[0].tools == {"search": ToolStatus.needs_approval}
    assert [b.id for b in spec.subagents[0].mcp_servers] == [child_binding.id]


async def test_all_mcp_bindings_spans_parent_and_subagents_without_deduping(
    agent_session,
):
    """The `collect_run_bindings` contract: a server configured on the parent but
    left unconfigured on a subagent must stay separately visible, so the
    readiness check can see the unconfigured one."""
    parent = await _add_agent(agent_session, "Parent")
    child = await _add_agent(agent_session, "Child")
    await _bind_subagent(agent_session, parent.id, child.id)
    shared_server_id = uuid4()
    agent_session.add(
        AgentMCPServerDB(
            agent_id=parent.id,
            mcp_server_id=shared_server_id,
            tools={"search": ToolStatus.always_allow},
        )
    )
    agent_session.add(
        AgentMCPServerDB(agent_id=child.id, mcp_server_id=shared_server_id, tools=None)
    )
    await agent_session.flush()

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    bindings = spec.all_mcp_bindings
    assert len(bindings) == 2
    assert {b.mcp_server_id for b in bindings} == {shared_server_id}
    assert sorted(b.tools is None for b in bindings) == [False, True]


async def test_carries_the_sandbox_row_so_the_runtime_need_not_refetch_it(
    agent_session,
):
    agent = await _add_agent(agent_session, "Parent")
    sandbox = await _bind_sandbox(
        agent_session, agent.id, {"execute": ToolStatus.always_allow}
    )

    spec = await AgentRepository(agent_session).get_run_spec(agent.id)

    assert spec is not None
    assert spec.agent.sandbox is not None
    assert spec.agent.sandbox.row.id == sandbox.id
    assert spec.agent.sandbox.row.url == "https://sandbox.example.com"
    assert spec.agent.sandbox.tools == {"execute": ToolStatus.always_allow}


@pytest.mark.parametrize("subagent_count", [0, 1, 5])
async def test_cost_is_flat_in_the_number_of_subagents(
    agent_session, statements, subagent_count
):
    """The reason this method exists. The path it replaces ran a full
    `AgentService.get` per agent — ~5 queries each, so (1+N)×5 — three times per
    send. Three queries, whatever N is."""
    parent = await _add_agent(agent_session, "Parent")
    await _bind_server(agent_session, parent.id)
    await _bind_sandbox(agent_session, parent.id)
    for i in range(subagent_count):
        child = await _add_agent(agent_session, f"Child {i}")
        await _bind_subagent(agent_session, parent.id, child.id)
        await _bind_server(agent_session, child.id)
    statements.reset()

    spec = await AgentRepository(agent_session).get_run_spec(parent.id)

    assert spec is not None
    assert len(spec.subagents) == subagent_count
    assert len(statements) == 3, "\n".join(statements.statements)
