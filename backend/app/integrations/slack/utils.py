import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, Request
from slack_sdk.web.async_client import AsyncWebClient

from app.database import AsyncSessionLocal
from app.integrations.slack.models import SlackUserInfo
from app.notifications.service import SlackNotificationSettingsService
from app.users.models import UserDB
from app.users.repository import UserRepository
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)

_MAX_AGE_SECONDS = 60 * 5


@dataclass(frozen=True)
class VerifiedSlackRequest:
    body: bytes
    workspace_id: UUID
    team_id: str


def _team_id(body: bytes) -> str | None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raw = parse_qs(body.decode()).get("payload", [None])[0]
        if raw is None:
            return None
        data = json.loads(raw)
    team = data.get("team")
    return data.get("team_id") or (team.get("id") if isinstance(team, dict) else None)


async def verify_slack_signature(
    request: Request,
    x_slack_request_timestamp: str = Header(...),
    x_slack_signature: str = Header(...),
) -> VerifiedSlackRequest:
    """FastAPI dependency that verifies the Slack request signature.

    Returns the raw request body so downstream handlers don't need to
    read it a second time.
    """
    timestamp = int(x_slack_request_timestamp)
    age = abs(time.time() - timestamp)
    if age > _MAX_AGE_SECONDS:
        raise HTTPException(status_code=403, detail="Request too old")

    body = await request.body()
    team_id = _team_id(body)
    if not team_id:
        raise HTTPException(status_code=403, detail="Unknown Slack workspace")
    async with AsyncSessionLocal() as db:
        config = await SlackNotificationSettingsService(db).get_runtime_config_for_team(
            team_id
        )
    if config is None:
        raise HTTPException(status_code=503, detail="Slack is not configured")

    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(
            config.signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    match = hmac.compare_digest(expected, x_slack_signature)

    if not match:
        raise HTTPException(status_code=403, detail="Invalid signature")

    return VerifiedSlackRequest(
        body=body, workspace_id=config.workspace_id, team_id=team_id
    )


async def get_slack_client(workspace_id: UUID) -> AsyncWebClient | None:
    async with AsyncSessionLocal() as db:
        config = await SlackNotificationSettingsService(db).get_runtime_config(
            workspace_id
        )
    return AsyncWebClient(token=config.bot_token) if config else None


async def get_user_info(user_id: str, workspace_id: UUID) -> SlackUserInfo | None:
    """Get user information from Slack API."""
    url = "https://slack.com/api/users.info"
    slack_client = await get_slack_client(workspace_id)
    if slack_client is None:
        return None
    headers = {"Authorization": f"Bearer {slack_client.token}"}
    params = {"user": user_id}

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(url, headers=headers, params=params)
            response.raise_for_status()

            data = response.json()
            if data.get("ok"):
                return SlackUserInfo.model_validate(data.get("user"))
            logger.warning("Slack API error (users.info): %s", data.get("error"))
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(
                "HTTP error calling Slack API (users.info): %s - %s",
                e.response.status_code,
                e.response.text,
            )
            return None
        except Exception:
            logger.exception("Unexpected error calling Slack API (users.info)")
            return None


async def resolve_user(slack_user_id: str, workspace_id: UUID) -> UserDB | None:
    """Map a Slack user ID to an internal user via email lookup."""
    user_info = await get_user_info(slack_user_id, workspace_id)
    if not user_info or not user_info.profile.email:
        return None
    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_email(user_info.profile.email)
        if user is None:
            return None
        membership = await WorkspaceRepository(db).get_membership(workspace_id, user.id)
        if membership is None:
            return None
        user.set_workspace_membership(membership)
        return user
