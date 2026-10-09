from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.notifications.models import SlackNotificationSettingsDB
from app.repository import BaseRepository
from app.utils.encryption import decrypt_value, encrypt_value


class SlackNotificationSettingsRepository(BaseRepository[SlackNotificationSettingsDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SlackNotificationSettingsDB, db)

    async def get_settings(
        self, workspace_id: UUID | None = None
    ) -> SlackNotificationSettingsDB | None:
        stmt = select(SlackNotificationSettingsDB).where(
            SlackNotificationSettingsDB.key == "default"
        )
        if workspace_id is not None:
            stmt = stmt.where(SlackNotificationSettingsDB.workspace_id == workspace_id)
        else:
            stmt = stmt.limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_credentials(
        self, workspace_id: UUID | None = None
    ) -> tuple[str, str] | None:
        row = await self.get_settings(workspace_id)
        if (
            row is None
            or not row.enabled
            or not row.bot_token_encrypted
            or not row.signing_secret_encrypted
        ):
            return None
        return (
            decrypt_value(row.bot_token_encrypted),
            decrypt_value(row.signing_secret_encrypted),
        )

    async def get_by_team_id(self, team_id: str) -> SlackNotificationSettingsDB | None:
        stmt = select(SlackNotificationSettingsDB).where(
            SlackNotificationSettingsDB.slack_team_id == team_id,
            SlackNotificationSettingsDB.enabled,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_configured(self) -> list[SlackNotificationSettingsDB]:
        stmt = select(SlackNotificationSettingsDB).where(
            SlackNotificationSettingsDB.enabled,
            col(SlackNotificationSettingsDB.slack_team_id).is_not(None),
            col(SlackNotificationSettingsDB.bot_token_encrypted).is_not(None),
            col(SlackNotificationSettingsDB.signing_secret_encrypted).is_not(None),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_or_create(self, workspace_id: UUID) -> SlackNotificationSettingsDB:
        row = await self.get_settings(workspace_id)
        if row is not None:
            return row
        try:
            async with self.db.begin_nested():
                row = SlackNotificationSettingsDB(workspace_id=workspace_id)
                self.db.add(row)
                await self.db.flush()
        except IntegrityError:
            row = await self.get_settings(workspace_id)
            if row is None:
                raise
        return row

    async def save(
        self,
        *,
        workspace_id: UUID,
        enabled: bool,
        bot_token: str | None,
        signing_secret: str | None,
        slack_team_id: str | None,
    ) -> SlackNotificationSettingsDB:
        row = await self._get_or_create(workspace_id)
        row.enabled = enabled
        row.slack_team_id = slack_team_id
        if bot_token is not None:
            row.bot_token_encrypted = encrypt_value(bot_token)
        if signing_secret is not None:
            row.signing_secret_encrypted = encrypt_value(signing_secret)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def clear(self, workspace_id: UUID) -> None:
        row = await self.get_settings(workspace_id)
        if row is not None:
            await self.db.delete(row)
        await self.db.flush()
