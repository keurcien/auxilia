from pydantic import BaseModel, Field


class SlackNotificationSettingsResponse(BaseModel):
    enabled: bool
    is_configured: bool
    bot_token_last4: str | None = None
    bot_token_length: int | None = None
    has_signing_secret: bool = False
    slack_team_id: str | None = None
    events_url: str
    interactions_url: str


class SlackNotificationSettingsUpdate(BaseModel):
    enabled: bool = True
    bot_token: str | None = Field(default=None, max_length=4096)
    signing_secret: str | None = Field(default=None, max_length=4096)
    slack_team_id: str | None = Field(default=None, max_length=64)
