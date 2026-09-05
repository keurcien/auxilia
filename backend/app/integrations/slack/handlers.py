# Handlers contain the business logic for each Slack event type.
#
# Threads are created when the user picks an agent via the agent picker
# (triggered by @auxilia mention). Subsequent messages in that thread are
# routed to the configured agent by *enqueuing a durable run* — the web tier
# never executes the agent itself (see `app/agents/runs/` and `consumer.py`).

import logging

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.hitl import (
    PendingInterrupt,
    load_interrupt_scope,
    pending_approval_requests,
)
from app.agents.runs.service import RunService
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import (
    DomainValidationError,
    ModelUnavailableError,
    StaleApprovalError,
)
from app.integrations.slack.blocks import build_connect_prompt_blocks
from app.integrations.slack.commands.chat import (
    build_agent_picker_blocks,
    list_pickable_agents,
    post_agent_picker,
)
from app.integrations.slack.consumer import build_slack_delivery
from app.integrations.slack.models import SlackEvent, SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info, resolve_user
from app.threads.models import ThreadDB
from app.users.repository import UserRepository


logger = logging.getLogger(__name__)


async def _enqueue_slack_run(
    *,
    thread_id: str,
    user_id: str,
    channel_id: str,
    slack_user_id: str,
    team_id: str | None,
    input: dict | None = None,
    command: dict | None = None,
) -> None:
    """Create a durable run for a Slack turn; the worker executes + delivers it.

    A duplicate that slips the webhook dedup races the per-thread mutex and is
    rejected at create time — swallowed here so Slack still gets a clean ack.
    """
    delivery = build_slack_delivery(
        channel_id=channel_id,
        thread_ts=thread_id,
        slack_user_id=slack_user_id,
        team_id=team_id,
    )
    try:
        await RunService().create(
            thread_id=thread_id,
            user_id=user_id,
            input=input,
            command=command,
            delivery=delivery,
        )
    except DomainValidationError:
        logger.info("Slack run for thread %s skipped: active run exists", thread_id)


# ---------------------------------------------------------------------------
# Approval-message introspection  (stateless — reads from the thread itself,
# keyed by the checkpoint's interrupt id via each card's block_id)
# ---------------------------------------------------------------------------

#: Marker text per decision — presentation only. The machine-readable copy of
#: the decision lives in the marker's block_id; nothing reads these emoji back
#: except the legacy scan over cards posted before the block-id protocol.
_DECISION_MARKERS = {
    "approve": ":white_check_mark: Approved",
    "reject": ":no_entry_sign: Rejected",
    "stale": ":information_source: Already handled elsewhere",
}


def _parse_hitl_block_id(
    block_id: object, *, decided: bool
) -> tuple[str, str, str | None] | None:
    """``hitl:<interrupt_id>:<tool_call_id>`` (pending) or
    ``hitl:<interrupt_id>:<tool_call_id>:<decision>`` (decided) → parts, or None.

    Whether a decision suffix exists is told by the block that carries the id
    (an actions block is pending by construction, a context marker is
    decided), never by string-matching the tail — so a tool_call_id that
    itself ends in ``:approve`` cannot make a pending card look decided. A
    marker's suffix is appended last, so for a decided card the segment after
    the final ``:`` is always the decision, even when the tool_call_id
    contains ``:``.
    """
    if not isinstance(block_id, str) or not block_id.startswith("hitl:"):
        return None
    interrupt_id, _, rest = block_id[len("hitl:") :].partition(":")
    if not interrupt_id or not rest:
        return None
    if not decided:
        return interrupt_id, rest, None
    tool_call_id, sep, decision = rest.rpartition(":")
    if not sep or decision not in _DECISION_MARKERS:
        return None
    return interrupt_id, tool_call_id, decision


def _card_interrupt_id(blocks: list[dict]) -> str | None:
    """The interrupt id a still-pending card was posted for, or None (legacy card)."""
    for block in blocks or []:
        if block.get("type") == "actions":
            parsed = _parse_hitl_block_id(block.get("block_id"), decided=False)
            if parsed:
                return parsed[0]
    return None


def _addressed_cards(
    messages: list[dict], interrupt_id: str
) -> tuple[dict[str, str], bool]:
    """(decided ``{tool_call_id: decision}``, any_pending) among the cards tagged
    with this interrupt id.

    Identity, not adjacency: an interleaved notice (a failure message, the
    "View in auxilia" link) can't truncate the batch, and cards left over from
    an older interrupt are ignored rather than miscounted.
    """
    decided: dict[str, str] = {}
    any_pending = False
    for msg in messages:
        for block in msg.get("blocks", []):
            block_type = block.get("type")
            if block_type == "actions":
                parsed = _parse_hitl_block_id(block.get("block_id"), decided=False)
                if parsed and parsed[0] == interrupt_id:
                    any_pending = True
            elif block_type == "context":
                parsed = _parse_hitl_block_id(block.get("block_id"), decided=True)
                if (
                    parsed
                    and parsed[0] == interrupt_id
                    # "stale" markers are neither pending nor decided.
                    and parsed[2] in ("approve", "reject")
                ):
                    decided[parsed[1]] = parsed[2]
    return decided, any_pending


# --- Legacy scan (cards posted before the block-id protocol carried no id;
# --- their decisions live only in the marker emoji). Delete once pre-block-id
# --- pending approvals have drained.


def _is_pending(msg: dict) -> bool:
    """Check if a message still has approval action buttons."""
    for block in msg.get("blocks", []):
        if block.get("type") == "actions" and any(
            el.get("action_id") in ("tool_approve", "tool_reject")
            for el in block.get("elements", [])
        ):
            return True
    return False


def _extract_decision(msg: dict) -> str | None:
    """Extract the decision from a decided approval message.

    The decision lives in the `context` block that `_update_approval_message`
    swaps in for the buttons; that block is the only one carrying the status emoji.
    """
    for block in msg.get("blocks", []):
        if block.get("type") != "context":
            continue
        text = " ".join(el.get("text", "") for el in block.get("elements", []))
        if ":white_check_mark:" in text:
            return "approve"
        if ":no_entry_sign:" in text:
            return "reject"
    return None


def _is_approval_message(msg: dict) -> bool:
    """Check if a message is an approval block (pending or decided)."""
    return _is_pending(msg) or _extract_decision(msg) is not None


def _get_latest_approval_batch(messages: list[dict]) -> list[dict]:
    """Return the trailing group of consecutive approval messages.

    Scans from the end of the thread backwards and collects all
    contiguous approval messages (pending or decided). Stops at
    the first non-approval message.
    """
    batch: list[dict] = []
    for msg in reversed(messages):
        if _is_approval_message(msg):
            batch.append(msg)
        else:
            if batch:
                break
    batch.reverse()
    return batch


def _collect_batch_decisions(thread_messages: list[dict]) -> list[str] | None:
    """Inspect the thread and return decisions if the latest batch is complete.

    Returns ``None`` if there are still pending approvals, or if no
    decided approvals were found.
    """
    batch = _get_latest_approval_batch(thread_messages)

    if any(_is_pending(msg) for msg in batch):
        return None

    commands = [d for msg in batch if (d := _extract_decision(msg)) is not None]
    return commands or None


async def _pending_hitl_state(
    thread_id: str,
) -> tuple[PendingInterrupt, list[dict]] | None:
    """The pending interrupt and its approval requests, from the checkpoint.

    The checkpoint is the source of truth for "this thread is waiting on
    approvals" — it is what makes a card clicked days later still resumable,
    and what exposes a card whose interrupt was already resolved elsewhere.
    """
    async with get_checkpointer() as checkpointer:
        scope = await load_interrupt_scope(checkpointer, thread_id)
    if scope is None:
        return None
    # A subagent's approvals are matched in its own checkpoint (`scope`).
    return scope.interrupt, pending_approval_requests(scope.root, scope.checkpoint)


def _collect_batch_command(
    thread_messages: list[dict],
    interrupt: PendingInterrupt,
    requests: list[dict],
    *,
    allow_legacy: bool,
) -> dict | None:
    """The resume command for the pending interrupt, once every card is decided.

    Prefers the addressed protocol — cards tagged ``hitl:<interrupt_id>:…`` —
    and builds the addressed resume (`interrupt_id` + tool-call-keyed
    decisions) that `RunService.create` validates and orders against the
    checkpoint. Returns None while any card is undecided, or when a card
    vanished and the batch can't complete — the web UI remains the escape
    hatch either way.

    The legacy emoji scan applies only when **both** the clicked card predates
    block ids (``allow_legacy``) and the pending interrupt itself carries no
    id: an untagged decided card cannot prove which interrupt it answered, so
    once the checkpoint identifies the interrupt, resuming it from unprovable
    cards could replay an **older batch's** decisions onto it — the exact bug
    the block-id protocol exists to kill. Those clicks are answered with a
    pointer to the web UI in `handle_interaction` instead.
    """
    if interrupt.id is not None:
        decided, any_pending = _addressed_cards(thread_messages, interrupt.id)
        if any_pending:
            return None
        expected = [r["tool_call_id"] for r in requests]
        if decided and set(expected) <= set(decided):
            return {
                "resume": {
                    "interrupt_id": interrupt.id,
                    "decisions": [
                        {"tool_call_id": tc, "type": decided[tc]} for tc in expected
                    ],
                }
            }
        # An identifiable interrupt with no complete tagged batch: nothing
        # here is safe to resume, whatever legacy cards the thread holds.
        return None
    if not allow_legacy:
        return None
    commands = _collect_batch_decisions(thread_messages)
    # The positional shape stands or falls with its length: a count mismatch
    # means these decisions answer some other batch, not this interrupt.
    if commands is None or len(commands) != len(requests):
        return None
    return {"resume": {"decisions": [{"type": c} for c in commands]}}


async def _update_approval_message(
    client: AsyncWebClient,
    channel_id: str,
    message_ts: str,
    blocks: list[dict],
    decision: str,
) -> None:
    """Record the decision: drop the buttons and append a status context block.

    The card no longer carries a tool-name header (the streamed label above it
    already shows it), so the decision marker lives in its own `context` block.
    The marker's ``block_id`` (the actions block's id plus a ``:<decision>``
    suffix) is what the batch-resume logic reads back; the emoji is
    presentation. A legacy card has no id to carry over — its emoji stays
    load-bearing for the legacy scan until those cards drain.
    """
    marker: dict = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": _DECISION_MARKERS[decision]}],
    }
    actions = next((b for b in blocks if b.get("type") == "actions"), None)
    if actions is not None and isinstance(actions.get("block_id"), str):
        marker["block_id"] = f"{actions['block_id']}:{decision}"
    # Replace the Approve/Reject buttons in place with the decision marker, so it
    # sits where the buttons were (above the trailing divider). A card that's
    # already decided has no actions block to replace, so it's left untouched.
    updated_blocks = [marker if b.get("type") == "actions" else b for b in blocks]

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=updated_blocks,
        text=_DECISION_MARKERS[decision].split(" ", 1)[1],
    )


# ---------------------------------------------------------------------------
# Top-level event handlers
# ---------------------------------------------------------------------------


async def handle_assistant_thread_started(event: SlackEvent) -> None:
    """Welcome a user when they open a new AI-assistant thread.

    Sets a typing status, resolves the Slack identity to an internal account,
    then either explains the problem or presents the agent picker.
    """
    at = event.assistant_thread
    if not at or not at.user_id or not at.channel_id or not at.thread_ts:
        return

    channel_id = at.channel_id
    thread_ts = at.thread_ts
    slack_user_id = at.user_id

    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    await client.assistant_threads_setStatus(
        channel_id=channel_id,
        thread_ts=thread_ts,
        status="is typing...",
    )

    user_info = await get_user_info(slack_user_id)
    display_name = (user_info.real_name or user_info.name) if user_info else "there"

    # Resolve Slack identity → internal user
    user = None
    if user_info and user_info.profile.email:
        async with AsyncSessionLocal() as db:
            user = await UserRepository(db).get_by_email(user_info.profile.email)

    if not user:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! It seems like you haven't registered on auxilia yet.",
        )
        return

    async with AsyncSessionLocal() as db:
        agents = await list_pickable_agents(db, user.id, user.role, user.team_id)

    if not agents:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! You don't have any agents configured yet.",
        )
        return

    blocks = build_agent_picker_blocks(
        agents,
        header_text=f"Hi {display_name}! Select an agent to begin a conversation:",
    )
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text=f"Hi {display_name}! Select an agent to begin a conversation.",
    )


async def _is_agent_ready(agent_id: str, user_id: str, db: AsyncSession) -> bool:
    """Mirror the /is-ready endpoint (including subagents' servers): True only
    when every bound MCP server is configured and connected for this user.

    Fail-open: these handlers run as fire-and-forget tasks (Slack is already
    acked), so an infra error here (Redis blip, DB hiccup) must not kill the
    task silently — let the run launch and fail visibly instead."""
    from uuid import UUID

    try:
        readiness = await AgentService(db).describe_readiness(UUID(agent_id), user_id)
    except Exception:  # noqa: BLE001 — fail-open, per the docstring above
        logger.warning(
            "Slack readiness check for agent %s failed; letting the run proceed",
            agent_id,
            exc_info=True,
        )
        return True
    return readiness["ready"]


async def _post_connect_prompt(
    client: AsyncWebClient, channel: str, thread_ts: str, agent_id
) -> None:
    """Tell the Slack user to (re)connect the agent's MCP servers on auxilia."""
    connect_url = f"{auth_settings.FRONTEND_URL}/agents/{agent_id}/chat"
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=build_connect_prompt_blocks(connect_url),
    )


async def handle_message(event: SlackEvent, *, team_id: str | None = None) -> None:
    """Route a Slack message to the configured agent by enqueuing a durable run."""
    thread_ts = event.thread_ts or event.ts

    question = (event.text or "").strip()
    if not question:
        return

    user = await resolve_user(event.user)

    if not user:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Look up the existing thread (created when the user picked an agent)
    async with AsyncSessionLocal() as db:
        thread = await db.get(ThreadDB, thread_ts)

        if not thread:
            await post_agent_picker(
                client,
                event.channel,
                thread_ts,
                db,
                user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
            return

        if not await _is_agent_ready(str(thread.agent_id), str(user.id), db):
            await _post_connect_prompt(
                client, event.channel, thread_ts, thread.agent_id
            )
            return

        await client.assistant_threads_setStatus(
            channel_id=event.channel,
            thread_ts=thread_ts,
            status="is typing...",
        )

        # Set the Slack thread title to the first real user message.
        if not thread.first_message_content:
            thread.first_message_content = question
            await db.commit()
            await client.assistant_threads_setTitle(
                channel_id=event.channel,
                thread_ts=thread_ts,
                title=question[:255],
            )

    try:
        await _enqueue_slack_run(
            thread_id=thread_ts,
            user_id=str(user.id),
            channel_id=event.channel,
            slack_user_id=event.user,
            team_id=team_id,
            input={"messages": [{"type": "human", "content": question}]},
        )
    except ModelUnavailableError as exc:
        # exc.detail carries the precise reason (disabled by admin / provider
        # key missing / removed from the catalog) — a fixed "ask an admin to
        # re-enable it" would be wrong advice for two of the three.
        await client.chat_postMessage(
            channel=event.channel,
            thread_ts=thread_ts,
            text=(
                f"{exc.detail} Ask a workspace admin about it, or start a "
                "new conversation."
            ),
        )


async def handle_interaction(payload: SlackInteractionPayload) -> None:
    """Handle a Slack block_actions interaction (Approve/Reject buttons).

    Approval state is derived from the thread itself (``conversations.replies``)
    and arbitrated by the checkpoint's pending interrupt — no external state
    store, no TTL, so a card clicked days later still works. The agent is
    resumed (via a new durable run) only once every card of the pending batch
    has been decided; a click on a card whose interrupt was already resolved
    elsewhere marks the card as handled and never resumes.
    """
    if not payload.actions:
        return

    action = payload.actions[0]
    if action.action_id not in ("tool_approve", "tool_reject"):
        return

    approved = action.action_id == "tool_approve"
    channel_id, thread_ts, message_ts = _extract_interaction_context(payload)
    if not channel_id or not thread_ts:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    original_blocks = payload.message.blocks if payload.message else []

    # The checkpoint arbitrates: which interrupt is pending, and is the
    # clicked card part of it? A card for a resolved interrupt (approved from
    # the web, an older batch) is marked, not counted.
    state = await _pending_hitl_state(thread_ts)
    card_interrupt_id = _card_interrupt_id(original_blocks)
    stale = state is None or (
        card_interrupt_id is not None
        and state[0].id is not None
        and card_interrupt_id != state[0].id
    )
    if stale:
        if message_ts:
            await _update_approval_message(
                client, channel_id, message_ts, original_blocks, "stale"
            )
        return

    interrupt, requests = state
    if card_interrupt_id is None and interrupt.id is not None:
        # A pre-block-id card clicked against an interrupt the checkpoint can
        # identify: nothing proves this card answers it, so never mark it or
        # resume from it — the buttons stay, and the web UI (which verifies
        # every resume against the checkpoint) takes over.
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                "This approval card predates an update and can't be matched "
                "to the pending request — please approve or reject it from "
                "auxilia."
            ),
        )
        return

    # Update the clicked message: buttons → status label
    if message_ts:
        await _update_approval_message(
            client,
            channel_id,
            message_ts,
            original_blocks,
            "approve" if approved else "reject",
        )

    # Check whether the pending batch is fully decided
    command = await _fetch_and_resolve_command(
        client,
        channel_id,
        thread_ts,
        interrupt,
        requests,
        allow_legacy=card_interrupt_id is None,
    )
    if command is None:
        return

    # All decided — resume the agent via a new run
    await _resume_agent(client, payload, channel_id, thread_ts, command)


def _extract_interaction_context(
    payload: SlackInteractionPayload,
) -> tuple[str | None, str | None, str | None]:
    """Extract channel_id, thread_ts, and message_ts from an interaction payload."""
    channel_id = (
        payload.channel.id
        if payload.channel
        else payload.container.channel_id
        if payload.container
        else None
    )
    thread_ts = payload.container.thread_ts if payload.container else None
    message_ts = payload.container.message_ts if payload.container else None
    return channel_id, thread_ts, message_ts


async def _fetch_and_resolve_command(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    interrupt: PendingInterrupt,
    requests: list[dict],
    *,
    allow_legacy: bool,
) -> dict | None:
    """Fetch thread replies and build the resume command if the batch is complete."""
    result = await client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
    )
    thread_messages = result.get("messages", [])
    return _collect_batch_command(
        thread_messages, interrupt, requests, allow_legacy=allow_legacy
    )


async def _resume_agent(
    client: AsyncWebClient,
    payload: SlackInteractionPayload,
    channel_id: str,
    thread_ts: str,
    command: dict,
) -> None:
    """Look up the thread and enqueue a HITL-resume run with *command*."""
    user = await resolve_user(payload.user.id)
    if not user:
        return

    async with AsyncSessionLocal() as db:
        thread = await db.get(ThreadDB, thread_ts)
        if not thread:
            return
        # Same gate as handle_message: an approval clicked after the user's
        # OAuth expired must prompt a reconnect, not enqueue a doomed run.
        if not await _is_agent_ready(str(thread.agent_id), str(user.id), db):
            await _post_connect_prompt(client, channel_id, thread_ts, thread.agent_id)
            return

    await client.assistant_threads_setStatus(
        channel_id=channel_id,
        thread_ts=thread_ts,
        status="is typing...",
    )

    try:
        await _enqueue_slack_run(
            thread_id=thread_ts,
            user_id=str(user.id),
            channel_id=channel_id,
            slack_user_id=payload.user.id,
            team_id=(payload.team or {}).get("id"),
            command=command,
        )
    except StaleApprovalError:
        # Lost the race with another surface between the checkpoint check in
        # `handle_interaction` and the enqueue — `RunService.create` is the
        # backstop. Nothing to resume; say so instead of failing silently.
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="This approval was already handled elsewhere.",
        )
    except ModelUnavailableError as exc:
        # The approval buttons stay in the thread and decisions are re-derived
        # from replies on every click, so re-approving after the model is
        # restored retries this resume — say so.
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                f"{exc.detail} Once it is available again, click the "
                "approval button again to resume."
            ),
        )
