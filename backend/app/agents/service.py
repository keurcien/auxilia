from sqlalchemy import select

from app.agents.models import AgentDB
from app.database import AsyncSessionLocal


async def get_all_agents() -> list[AgentDB]:
    """Return all agents."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentDB))
        return list(result.scalars().all())


async def get_agent_by_alias(alias: str) -> AgentDB | None:
    """Return the agent whose derived alias matches *alias*, or ``None``."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentDB))
        agents = result.scalars().all()
    for agent in agents:
        if agent.name.lower().replace(" ", "_") == alias:
            return agent
    return None
