import hashlib
import hmac
import time
import httpx
from typing import Optional
from fastapi import Header, HTTPException, Request
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.models import SlackUserInfo

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
    if abs(time.time() - timestamp) > _MAX_AGE_SECONDS:
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

    if not hmac.compare_digest(expected, x_slack_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    return body


async def get_user_info(user_id: str) -> Optional[SlackUserInfo]:
    """Get user information from Slack API."""
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {slack_settings.slack_bot_token}"}
    params = {"user": user_id}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()

            data = response.json()
            if data.get("ok"):
                return SlackUserInfo.model_validate(data.get("user"))
            else:
                print(f"Slack API error (users.info): {data.get('error')}")
                return None
        except httpx.HTTPStatusError as e:
            print(
                f"HTTP error calling Slack API (users.info): {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            print(
                f"An unexpected error occurred calling Slack API (users.info): {e}")
            return None
