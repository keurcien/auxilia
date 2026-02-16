# Slack endpoint router.
#
# Handles three types of incoming requests from Slack:
#
#   1. /events — event subscriptions (messages, mentions, etc.)
#   2. /interactions — interactive components (buttons, shortcuts, etc.)

import asyncio
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.integrations.slack.commands.chat import handle_agent_selection, handle_app_mention
from app.integrations.slack.handlers import handle_interaction, handle_message
from app.integrations.slack.models import SlackEventPayload, SlackInteractionPayload
from app.integrations.slack.utils import verify_slack_signature

router = APIRouter(prefix="/integrations/slack", tags=["slack"])

# In-memory set of message timestamps already dispatched.
# Prevents duplicate processing when Slack retries before the
# background task completes.
_seen_message_ts: set[str] = set()
_MAX_SEEN = 200


@router.post("/events")
async def slack_events(body: bytes = Depends(verify_slack_signature)):

    payload = SlackEventPayload.model_validate(json.loads(body))

    if payload.type == "url_verification":
        return JSONResponse(content={"challenge": payload.challenge})

    if payload.event.type == "app_mention" and payload.event.user:
        asyncio.create_task(
            handle_app_mention(payload.event, team_id=payload.team_id),
        )

    elif payload.event.type == "message" and payload.event.user:
        if payload.event.bot_id or payload.event.subtype == "bot_message":
            return JSONResponse(content={})

        ts = payload.event.ts
        if ts in _seen_message_ts:
            return JSONResponse(content={"ok": True})

        _seen_message_ts.add(ts)
        if len(_seen_message_ts) > _MAX_SEEN:
            _seen_message_ts.clear()

        asyncio.create_task(
            handle_message(payload.event, team_id=payload.team_id),
        )

    return JSONResponse(content={"ok": True})


@router.post("/interactions")
async def slack_interactions(body: bytes = Depends(verify_slack_signature)):
    """Handle Slack interactive component callbacks (buttons, shortcuts, etc.)."""
    form_data = parse_qs(body.decode())

    raw_payload = form_data.get("payload", [None])[0]
    if not raw_payload:
        return JSONResponse(content={"ok": True})

    payload = SlackInteractionPayload.model_validate(json.loads(raw_payload))

    if payload.type == "block_actions":
        action = payload.actions[0] if payload.actions else None
        if action and action.action_id.startswith("select_agent:"):
            asyncio.create_task(handle_agent_selection(payload))
        elif action and action.action_id in ("tool_approve", "tool_reject"):
            asyncio.create_task(handle_interaction(payload))

    return JSONResponse(content={"ok": True})
