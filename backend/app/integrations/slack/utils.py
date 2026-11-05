import asyncio
import hashlib
import hmac
import logging
import time

import httpx
from fastapi import Header, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.database import AsyncSessionLocal
from app.integrations.slack.models import SlackUserInfo
from app.integrations.slack.settings import slack_settings
from app.redis_client import get_redis
from app.users.models import UserDB
from app.users.repository import UserRepository


logger = logging.getLogger(__name__)

_MAX_AGE_SECONDS = 60 * 5


async def verify_slack_signature(
    request: Request,
    x_slack_request_timestamp: str = Header(...),
    x_slack_signature: str = Header(...),
) -> bytes:
    """FastAPI dependency that verifies the Slack request signature.

    Returns the raw request body so downstream handlers don't need to
    read it a second time.
    """
    timestamp = int(x_slack_request_timestamp)
    age = abs(time.time() - timestamp)
    if age > _MAX_AGE_SECONDS:
        raise HTTPException(status_code=403, detail="Request too old")

    body = await request.body()

    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(
            slack_settings.slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    match = hmac.compare_digest(expected, x_slack_signature)

    if not match:
        raise HTTPException(status_code=403, detail="Invalid signature")

    return body


async def get_user_info(user_id: str) -> SlackUserInfo | None:
    """Cache Slack identity for five minutes; permissions still come from the DB.

    Picker-opening events warm this shared cache before typeahead requests.
    Namespace by bot token so replacing a workspace connection cannot reuse
    another workspace's identities. Cache failures fall back to Slack.
    """
    token_hash = hashlib.sha256(slack_settings.slack_bot_token.encode()).hexdigest()
    cache_key = f"slack:user-info:{token_hash}:{user_id}"
    try:
        async with asyncio.timeout(0.2):
            cached = await get_redis().get(cache_key)
        if cached:
            return SlackUserInfo.model_validate_json(cached)
    except (RedisError, TimeoutError, ValidationError):
        logger.warning("Slack identity cache read failed", exc_info=True)
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {slack_settings.slack_bot_token}"}
    params = {"user": user_id}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()

            data = response.json()
            if data.get("ok"):
                user = SlackUserInfo.model_validate(data.get("user"))
                try:
                    async with asyncio.timeout(0.2):
                        await get_redis().set(cache_key, user.model_dump_json(), ex=300)
                except (RedisError, TimeoutError):
                    logger.warning("Slack identity cache write failed", exc_info=True)
                return user
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


async def resolve_user(slack_user_id: str) -> UserDB | None:
    """Map a Slack user ID to an internal user via email lookup."""
    user_info = await get_user_info(slack_user_id)
    if not user_info or not user_info.profile.email:
        return None
    async with AsyncSessionLocal() as db:
        return await UserRepository(db).get_by_email(user_info.profile.email)
