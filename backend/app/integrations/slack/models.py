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


class SlackEventPayload(BaseModel):
    """Top-level payload Slack sends to our endpoint."""
    type: str
    token: str | None = None
    challenge: str | None = None
    team_id: str | None = None
    event: SlackEvent | None = None


class SlackUserProfile(BaseModel):
    email: str


class SlackUserInfo(BaseModel):
    id: str
    name: str
    profile: SlackUserProfile
