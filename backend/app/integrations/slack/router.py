# Slack events endpoint.
#
# Slack sends all events to a single URL. This router handles:
#
#   1. url_verification — the initial handshake when registering
#      the Request URL in the Slack app settings.
#
#   2. event_callback — actual events (messages, mentions, etc.)
#      dispatched to the appropriate handler.
#
# All requests are verified via the signing-secret dependency
# before any processing takes place.

import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.integrations.slack.handlers import handle_message
from app.integrations.slack.models import SlackEventPayload
from app.integrations.slack.utils import verify_slack_signature

router = APIRouter(prefix="/integrations/slack", tags=["slack"])


@router.post("/events")
async def slack_events(body: bytes = Depends(verify_slack_signature)):
    payload = SlackEventPayload.model_validate(json.loads(body))

    if payload.type == "url_verification":
        return JSONResponse(content={"challenge": payload.challenge})

    if payload.event.type == "message" and payload.event.user:
        if payload.event.bot_id or payload.event.subtype == "bot_message":
            return JSONResponse(content={})

        await handle_message(payload.event, team_id=payload.team_id)

    return JSONResponse(content={"ok": True})
