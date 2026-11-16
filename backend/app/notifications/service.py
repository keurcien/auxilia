import hashlib
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.appearance.service import InstanceAppearanceService
from app.database import get_db
from app.exceptions import DomainValidationError
from app.notifications.repository import (
    SlackNotificationSettingsRepository,
    WebPushDeliveryRepository,
    WebPushSubscriptionRepository,
)
from app.notifications.schemas import (
    SlackNotificationSettingsResponse,
    SlackNotificationSettingsUpdate,
    WebPushConfigResponse,
    WebPushSubscriptionResponse,
    WebPushSubscriptionUpsert,
)
from app.notifications.settings import web_push_settings
from app.threads.models import ThreadDB
from app.users.repository import UserRepository
from app.utils.encryption import encrypt_value


class SlackNotificationSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SlackNotificationSettingsRepository(db)

    async def get_response(
        self, workspace_id: UUID
    ) -> SlackNotificationSettingsResponse:
        row = await self.repository.get_settings(workspace_id)
        return SlackNotificationSettingsResponse(enabled=bool(row and row.enabled))

    async def update(
        self, workspace_id: UUID, data: SlackNotificationSettingsUpdate
    ) -> SlackNotificationSettingsResponse:
        await self.repository.save(
            workspace_id=workspace_id,
            enabled=data.enabled,
        )
        return await self.get_response(workspace_id)


def get_slack_notification_settings_service(
    db: AsyncSession = Depends(get_db),
) -> SlackNotificationSettingsService:
    return SlackNotificationSettingsService(db)


def _endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


class WebPushSubscriptionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = WebPushSubscriptionRepository(db)

    @staticmethod
    def config() -> WebPushConfigResponse:
        return WebPushConfigResponse(
            enabled=web_push_settings.enabled,
            public_key=(
                web_push_settings.vapid_public_key
                if web_push_settings.enabled
                else None
            ),
        )

    async def upsert(
        self,
        user_id: UUID,
        data: WebPushSubscriptionUpsert,
    ) -> WebPushSubscriptionResponse:
        if not web_push_settings.enabled:
            raise DomainValidationError(
                "Web Push is not configured on this deployment."
            )
        await self.repository.upsert(
            user_id=user_id,
            endpoint_hash=_endpoint_hash(data.endpoint),
            endpoint_encrypted=encrypt_value(data.endpoint),
            p256dh_encrypted=encrypt_value(data.keys.p256dh),
            auth_encrypted=encrypt_value(data.keys.auth),
            user_agent=data.user_agent,
        )
        return WebPushSubscriptionResponse(subscribed=True)

    async def delete(
        self,
        user_id: UUID,
        endpoint: str,
    ) -> WebPushSubscriptionResponse:
        await self.repository.delete_for_user(user_id, _endpoint_hash(endpoint))
        return WebPushSubscriptionResponse(subscribed=False)


def get_web_push_subscription_service(
    db: AsyncSession = Depends(get_db),
) -> WebPushSubscriptionService:
    return WebPushSubscriptionService(db)


async def stage_run_web_push_deliveries(
    db: AsyncSession,
    *,
    run_id: str,
    status: str,
    user_id: UUID,
    thread: ThreadDB,
) -> None:
    if not web_push_settings.enabled:
        return
    copy = {
        "success": (
            "Response ready",
            "Your agent has finished responding.",
        ),
        "interrupted": (
            "Action required",
            "Your agent needs your input.",
        ),
        "error": (
            "Run failed",
            "Your agent could not finish the response.",
        ),
        "timeout": (
            "Run timed out",
            "Your agent took too long to respond.",
        ),
    }.get(status)
    if copy is None:
        return
    # The thread's own choice (seeded from the account default, and from the
    # trigger's setting for trigger firings) decides.
    enabled = thread.notifications_enabled
    if enabled is None:
        user = await UserRepository(db).get(user_id)
        enabled = user is not None and user.notifications_enabled
    if not enabled:
        return
    agent = await AgentRepository(db, thread.workspace_id).get_scoped(thread.agent_id)
    agent_name = agent.name if agent is not None else "Agent"
    query = urlencode(
        {
            "workspaceId": str(thread.workspace_id),
            "agentId": str(thread.agent_id),
            "threadId": thread.id,
        }
    )
    title, body = copy
    appearance = await InstanceAppearanceService(db).get_settings()
    payload = {
        "title": (
            f"{agent_name} answered"
            if status == "success"
            else f"{agent_name}: {title}"
        ),
        "body": body,
        "tag": f"run:{run_id}",
        "icon": "/pwa-icon-192.png",
        "data": {
            "runId": run_id,
            "threadId": thread.id,
            "url": f"/notifications/open?{query}",
        },
    }
    if appearance is not None and appearance.notification_badge_revision is not None:
        payload["badge"] = (
            "/api/backend/appearance/notification-badge/"
            f"{appearance.notification_badge_revision}"
        )
    await WebPushDeliveryRepository(db).enqueue_for_user(
        user_id=user_id,
        run_id=run_id,
        payload=payload,
    )
