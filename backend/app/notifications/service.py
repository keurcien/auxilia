from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.settings import auth_settings
from app.database import get_db
from app.exceptions import DomainValidationError
from app.notifications.repository import SlackNotificationSettingsRepository
from app.notifications.schemas import (
    SlackNotificationSettingsResponse,
    SlackNotificationSettingsUpdate,
)


@dataclass(frozen=True)
class SlackRuntimeConfig:
    workspace_id: UUID
    slack_team_id: str
    bot_token: str
    signing_secret: str


class SlackNotificationSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SlackNotificationSettingsRepository(db)

    async def get_runtime_config(self, workspace_id: UUID) -> SlackRuntimeConfig | None:
        row = await self.repository.get_settings(workspace_id)
        credentials = await self.repository.get_credentials(workspace_id)
        if credentials is None or row is None or not row.slack_team_id:
            return None
        return SlackRuntimeConfig(
            workspace_id=workspace_id,
            slack_team_id=row.slack_team_id,
            bot_token=credentials[0],
            signing_secret=credentials[1],
        )

    async def get_runtime_config_for_team(
        self, team_id: str
    ) -> SlackRuntimeConfig | None:
        row = await self.repository.get_by_team_id(team_id)
        if row is None:
            return None
        return await self.get_runtime_config(row.workspace_id)

    async def get_response(
        self, workspace_id: UUID
    ) -> SlackNotificationSettingsResponse:
        row = await self.repository.get_settings(workspace_id)
        credentials = await self.repository.get_credentials(workspace_id)
        bot_token = credentials[0] if credentials else None
        base = f"{auth_settings.FRONTEND_URL}/api/backend/integrations/slack"
        return SlackNotificationSettingsResponse(
            enabled=bool(row and row.enabled),
            is_configured=credentials is not None,
            bot_token_last4=bot_token[-4:] if bot_token else None,
            bot_token_length=len(bot_token) if bot_token else None,
            has_signing_secret=credentials is not None,
            slack_team_id=row.slack_team_id if row else None,
            events_url=f"{base}/events",
            interactions_url=f"{base}/interactions",
        )

    async def update(
        self, workspace_id: UUID, data: SlackNotificationSettingsUpdate
    ) -> SlackNotificationSettingsResponse:
        existing = await self.repository.get_settings(workspace_id)
        has_existing_pair = bool(
            existing
            and existing.bot_token_encrypted
            and existing.signing_secret_encrypted
        )
        bot_token = data.bot_token.strip() if data.bot_token is not None else None
        signing_secret = (
            data.signing_secret.strip() if data.signing_secret is not None else None
        )
        if (bot_token is None) != (signing_secret is None):
            raise DomainValidationError(
                "Slack bot token and signing secret must be updated together"
            )
        if bot_token is not None and not bot_token:
            raise DomainValidationError("Slack credentials cannot be empty")
        if signing_secret is not None and not signing_secret:
            raise DomainValidationError("Slack credentials cannot be empty")
        if data.enabled and not has_existing_pair and bot_token is None:
            raise DomainValidationError("Slack credentials are required")
        slack_team_id = (
            data.slack_team_id.strip()
            if data.slack_team_id is not None
            else existing.slack_team_id
            if existing
            else None
        )
        if bot_token is not None and not slack_team_id:
            try:
                auth = await AsyncWebClient(token=bot_token).auth_test()
                resolved_team_id = auth.get("team_id")
            except Exception as exc:
                raise DomainValidationError(
                    "Could not resolve the Slack workspace from the bot token"
                ) from exc
            if not isinstance(resolved_team_id, str) or not resolved_team_id:
                raise DomainValidationError(
                    "Slack did not return a workspace id for this bot token"
                )
            slack_team_id = resolved_team_id
        await self.repository.save(
            workspace_id=workspace_id,
            enabled=data.enabled,
            bot_token=bot_token,
            signing_secret=signing_secret,
            slack_team_id=slack_team_id,
        )
        return await self.get_response(workspace_id)

    async def clear(self, workspace_id: UUID) -> SlackNotificationSettingsResponse:
        await self.repository.clear(workspace_id)
        return await self.get_response(workspace_id)


def get_slack_notification_settings_service(
    db: AsyncSession = Depends(get_db),
) -> SlackNotificationSettingsService:
    return SlackNotificationSettingsService(db)
