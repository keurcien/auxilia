from typing import Any

from pydantic import BaseModel, Field


class AgentSlackBotUpdate(BaseModel):
    enabled: bool = True
    require_mention_in_threads: bool = True
    show_tool_callouts: bool = True
    bot_token: str | None = Field(default=None, max_length=4096)
    signing_secret: str | None = Field(default=None, max_length=4096)


class AgentSlackBotResponse(BaseModel):
    workspace_enabled: bool
    enabled: bool
    require_mention_in_threads: bool
    show_tool_callouts: bool
    is_configured: bool
    bot_token_last4: str | None = None
    has_signing_secret: bool = False
    slack_team_id: str | None = None
    slack_team_name: str | None = None
    bot_user_id: str | None = None
    bot_name: str | None = None
    events_url: str
    interactions_url: str
    manifest: dict[str, Any]
