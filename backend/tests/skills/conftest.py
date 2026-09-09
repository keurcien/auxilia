"""A real SQLite database for the skills tests, reusing the agents fixture's
engine (its table closure includes `skills` and `agent_skills`)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agents.models import AgentDB, AgentSubagentDB
from app.skills.bundles import parse_skill
from app.skills.models import AgentSkillDB, SkillDB
from app.skills.schemas import SkillFile
from app.users.models import UserDB, WorkspaceRole
from tests.agents.conftest import agent_engine, agent_session, statements  # noqa: F401
from tests.agents.test_runtime_behaviour import in_memory_runtime  # noqa: F401


def skill_markdown(name: str = "report", description: str = "Write a report") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nDo it.\n"


def make_user(role: WorkspaceRole = WorkspaceRole.member) -> UserDB:
    return UserDB(
        id=uuid4(),
        name="Someone",
        email=f"{uuid4()}@test.com",
        role=role,
        password_hash="x",
    )


async def seed_skill(
    session,
    *,
    owner_id,
    name: str = "report",
    files: list[SkillFile] | None = None,
) -> SkillDB:
    bundle = parse_skill(skill_markdown(name), files or [])
    row = SkillDB(
        owner_id=owner_id,
        name=bundle.name,
        description=bundle.description,
        content=bundle.content,
        files=[f.model_dump(mode="json") for f in bundle.files],
    )
    session.add(row)
    await session.flush()
    return row


async def seed_agent(session, *, owner_id=None) -> AgentDB:
    agent = AgentDB(
        name="Agent",
        instructions="Be helpful",
        owner_id=owner_id or uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(agent)
    await session.flush()
    return agent


async def attach(session, agent_id, skill_id) -> None:
    session.add(AgentSkillDB(agent_id=agent_id, skill_id=skill_id))
    await session.flush()


async def link_subagent(session, supervisor_id, subagent_id) -> None:
    session.add(AgentSubagentDB(supervisor_id=supervisor_id, subagent_id=subagent_id))
    await session.flush()


@pytest.fixture
def member() -> UserDB:
    return make_user()


@pytest.fixture
def admin() -> UserDB:
    return make_user(WorkspaceRole.admin)
