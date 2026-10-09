from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.integrations.slack.db_models import AgentSlackBotDB, SlackThreadBindingDB
from app.repository import BaseRepository


class AgentSlackBotRepository(BaseRepository[AgentSlackBotDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentSlackBotDB, db)

    async def get_for_agent(
        self, workspace_id: UUID, agent_id: UUID
    ) -> AgentSlackBotDB | None:
        stmt = select(AgentSlackBotDB).where(
            AgentSlackBotDB.workspace_id == workspace_id,
            AgentSlackBotDB.agent_id == agent_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_runtime(self, bot_id: UUID) -> AgentSlackBotDB | None:
        stmt = select(AgentSlackBotDB).where(AgentSlackBotDB.id == bot_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_installation(
        self, slack_team_id: str, bot_user_id: str
    ) -> AgentSlackBotDB | None:
        stmt = select(AgentSlackBotDB).where(
            AgentSlackBotDB.slack_team_id == slack_team_id,
            AgentSlackBotDB.bot_user_id == bot_user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class SlackThreadBindingRepository(BaseRepository[SlackThreadBindingDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SlackThreadBindingDB, db)

    async def get_external(
        self, slack_bot_id: UUID, channel_id: str, slack_thread_ts: str
    ) -> SlackThreadBindingDB | None:
        stmt = select(SlackThreadBindingDB).where(
            SlackThreadBindingDB.slack_bot_id == slack_bot_id,
            SlackThreadBindingDB.channel_id == channel_id,
            SlackThreadBindingDB.slack_thread_ts == slack_thread_ts,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_thread(self, thread_id: str) -> SlackThreadBindingDB | None:
        stmt = select(SlackThreadBindingDB).where(
            SlackThreadBindingDB.thread_id == thread_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
