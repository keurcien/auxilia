# Pydantic models for Slack webhook payloads.
#
# Slack sends different event shapes depending on the type. The two
# we care about for now:
#
#   - url_verification: Slack sends this once when you first register
#     your Request URL. We must respond with the challenge value.
#
#   - event_callback: wraps the actual event (message, app_mention, etc.)
#     The inner event is in the "event" field.
#
# As more event types are handled, add their inner-event models here.

from pydantic import BaseModel


class SlackAssistantThread(BaseModel):
    """Nested object present in both assistant_thread_started and message events.

    In assistant_thread_started the full context is provided (user_id, channel_id,
    thread_ts).  In regular message events only action_token is present, so all
    fields are optional.
    """
    user_id: str | None = None
    channel_id: str | None = None
    thread_ts: str | None = None


class SlackEvent(BaseModel):
    """The inner event object inside an event_callback payload."""
    type: str
    channel: str | None = None
    user: str | None = None
    text: str | None = None
    ts: str | None = None
    bot_id: str | None = None
    subtype: str | None = None
    thread_ts: str | None = None
    assistant_thread: SlackAssistantThread | None = None


class SlackEventPayload(BaseModel):
    """Top-level payload Slack sends to our endpoint."""
    type: str
    token: str | None = None
    challenge: str | None = None
    team_id: str | None = None
    event: SlackEvent | None = None


class SlackAction(BaseModel):
    """A single action from a block_actions interaction payload."""
    action_id: str
    value: str | None = None


class SlackInteractionChannel(BaseModel):
    id: str


class SlackInteractionUser(BaseModel):
    id: str


class SlackInteractionContainer(BaseModel):
    thread_ts: str | None = None
    channel_id: str | None = None
    message_ts: str | None = None


class SlackInteractionMessage(BaseModel):
    """The original message that contained the interactive component."""
    blocks: list[dict] = []
    thread_ts: str | None = None
    ts: str | None = None


class SlackInteractionPayload(BaseModel):
    """Payload Slack sends for interactive components and message shortcuts."""
    type: str
    user: SlackInteractionUser
    channel: SlackInteractionChannel | None = None
    actions: list[SlackAction] = []
    container: SlackInteractionContainer | None = None
    message: SlackInteractionMessage | None = None
    message_ts: str | None = None
    callback_id: str | None = None
    team: dict | None = None


class SlackUserProfile(BaseModel):
    email: str


class SlackUserInfo(BaseModel):
    id: str
    name: str
    real_name: str | None = None
    profile: SlackUserProfile
