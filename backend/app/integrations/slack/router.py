import asyncio
import json
import logging
from collections.abc import Coroutine
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.integrations.slack.commands.chat import handle_agent_selection
from app.integrations.slack.handlers import (
    handle_agent_message,
    handle_assistant_thread_started,
    handle_interaction,
    handle_message,
)
from app.integrations.slack.models import SlackEventPayload, SlackInteractionPayload
from app.integrations.slack.utils import (
    VerifiedSlackRequest,
    verify_agent_slack_signature,
    verify_slack_signature,
)
from app.redis_client import get_redis


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/slack", tags=["slack"])

# Slack requires an ack within 3s, so every handler runs as a detached task after
# the response. The event loop keeps only a weak reference to a running task, so
# without an owning set CPython may garbage-collect one mid-flight — and this is
# our only Slack execution path. Discard on completion so the set can't grow.
_background_tasks: set[asyncio.Task[None]] = set()

# Long enough to cover Slack's retry window (it retries a delivery it believes
# failed up to 3 times over ~30 minutes), short enough not to accumulate keys.
_DEDUP_TTL_SECONDS = 1800


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Run a handler detached from the request, keeping a strong reference."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def finish(completed: asyncio.Task[None]) -> None:
        _background_tasks.discard(completed)
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            logger.error(
                "Slack background handler failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(finish)


async def _claim_delivery(key: str) -> bool:
    """Claim a Slack delivery exactly once, across instances.

    Slack re-delivers an event it believes we failed to ack, and the backend runs
    several instances — a per-process `seen` set lets the retry land on a second
    instance and run the agent a second time. `SET NX EX` makes the claim atomic
    and shared.

    Fails open: if Redis is unreachable, process the event. A duplicate reply is
    a much smaller failure than silently dropping the user's message.
    """
    try:
        return bool(await get_redis().set(key, "1", nx=True, ex=_DEDUP_TTL_SECONDS))
    except RedisError:
        logger.warning(
            "Slack dedup claim for %s failed; processing anyway", key, exc_info=True
        )
        return True


@router.post("/events")
async def slack_events(
    verified: VerifiedSlackRequest = Depends(verify_slack_signature),
):
    payload = SlackEventPayload.model_validate(json.loads(verified.body))

    if payload.type == "url_verification":
        return JSONResponse(content={"challenge": payload.challenge})

    event = payload.event
    if event is None:
        # `event` is absent on payloads we don't handle (and on malformed ones).
        # Ack instead of raising: a 500 here makes Slack retry the same broken
        # callback for its whole retry window.
        logger.info("Slack callback %r carried no event; ignoring", payload.type)
        return JSONResponse(content={"ok": True})

    if event.type == "assistant_thread_started":
        _spawn(handle_assistant_thread_started(event, verified.workspace_id))

    elif event.type == "message" and event.user:
        if event.bot_id or event.subtype == "bot_message":
            return JSONResponse(content={})

        if event.ts and not await _claim_delivery(
            f"slack:event:{payload.team_id}:{event.channel}:{event.ts}"
        ):
            return JSONResponse(content={"ok": True})

        _spawn(
            handle_message(
                event,
                workspace_id=verified.workspace_id,
                team_id=payload.team_id,
            )
        )

    return JSONResponse(content={"ok": True})


@router.post("/agents/{agent_id}/events")
async def agent_slack_events(
    verified: VerifiedSlackRequest = Depends(verify_agent_slack_signature),
):
    payload = SlackEventPayload.model_validate(json.loads(verified.body))
    if payload.type == "url_verification":
        return JSONResponse(content={"challenge": payload.challenge})

    event = payload.event
    if (
        event is None
        or verified.agent_id is None
        or verified.slack_bot_id is None
        or event.type not in ("app_mention", "message")
        or not event.user
    ):
        return JSONResponse(content={"ok": True})
    if event.bot_id or event.subtype == "bot_message":
        return JSONResponse(content={"ok": True})
    if (
        event.type == "message"
        and event.channel_type != "im"
        and (event.thread_ts is None or verified.require_mention_in_threads)
    ):
        # `message.channels` also carries mentions. Let the matching
        # `app_mention` event own them so a duplicate callback cannot consume
        # the shared timestamp dedup key before the actionable event arrives.
        return JSONResponse(content={"ok": True})
    if event.ts and not await _claim_delivery(
        f"slack:agent:{verified.slack_bot_id}:{event.channel}:{event.ts}"
    ):
        return JSONResponse(content={"ok": True})
    _spawn(
        handle_agent_message(
            event,
            workspace_id=verified.workspace_id,
            agent_id=verified.agent_id,
            slack_bot_id=verified.slack_bot_id,
            team_id=payload.team_id,
            integration_enabled=verified.integration_enabled,
            require_mention_in_threads=verified.require_mention_in_threads,
        )
    )
    return JSONResponse(content={"ok": True})


@router.post("/interactions")
async def slack_interactions(
    verified: VerifiedSlackRequest = Depends(verify_slack_signature),
):
    """Handle Slack interactive component callbacks (buttons, shortcuts, etc.)."""
    form_data = parse_qs(verified.body.decode())

    raw_payload = form_data.get("payload", [None])[0]
    if not raw_payload:
        return JSONResponse(content={"ok": True})

    payload = SlackInteractionPayload.model_validate(json.loads(raw_payload))

    if payload.type == "block_actions":
        action = payload.actions[0] if payload.actions else None
        if action and action.action_id == "select_agent":
            _spawn(handle_agent_selection(payload, verified.workspace_id))
        elif action and action.action_id in ("tool_approve", "tool_reject"):
            _spawn(handle_interaction(payload, verified.workspace_id))

    return JSONResponse(content={"ok": True})


@router.post("/agents/{agent_id}/interactions")
async def agent_slack_interactions(
    verified: VerifiedSlackRequest = Depends(verify_agent_slack_signature),
):
    if not verified.integration_enabled:
        return JSONResponse(content={"ok": True})
    form_data = parse_qs(verified.body.decode())
    raw_payload = form_data.get("payload", [None])[0]
    if not raw_payload or verified.agent_id is None or verified.slack_bot_id is None:
        return JSONResponse(content={"ok": True})
    payload = SlackInteractionPayload.model_validate(json.loads(raw_payload))
    if payload.type == "block_actions":
        action = payload.actions[0] if payload.actions else None
        if action and action.action_id in ("tool_approve", "tool_reject"):
            _spawn(
                handle_interaction(
                    payload,
                    verified.workspace_id,
                    slack_bot_id=verified.slack_bot_id,
                    agent_id=verified.agent_id,
                )
            )
    return JSONResponse(content={"ok": True})
