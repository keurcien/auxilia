"""Freeze skill versions before a worker starts or resumes execution."""

from app.agents.core.repository import AgentRepository
from app.skills.repository import SkillRepository
from app.skills.runtime import resolve_skills


async def prepare_run_skills(db, record, thread):
    if record.skill_snapshot is not None:
        return record.skill_snapshot
    snapshot = None
    if record.command is not None:
        snapshot = await SkillRepository(db).interrupted_snapshot(record)
    if snapshot is None:
        spec = await AgentRepository(db).get_run_spec(thread.agent_id)
        snapshot = {}
        for agent in [spec.agent, *spec.subagents]:
            snapshot[str(agent.id)] = await resolve_skills(
                db, agent, str(record.user_id), thread.id
            )
    await SkillRepository(db).freeze_snapshot(record, snapshot)
    return snapshot
