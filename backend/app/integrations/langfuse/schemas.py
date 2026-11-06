from datetime import datetime

from sqlmodel import Field, SQLModel


class LangfuseStatusResponse(SQLModel):
    enabled: bool


class LangfusePromptVersion(SQLModel):
    version: int
    labels: list[str]
    commit_message: str | None = None
    text: str
    author: str | None = None
    created_at: datetime | None = None
    # Compared on publish to skip a no-op version; not part of the API.
    config: dict | None = Field(default=None, exclude=True)


class LangfusePromptResponse(SQLModel):
    """The agent's production prompt, and whether the instructions still match it."""

    production: LangfusePromptVersion | None
    diverged: bool


class LangfusePublishDraft(SQLModel):
    """What a publish would send: the computed config, and the prompt's labels."""

    config_json: str
    labels: list[str]


class LangfusePublishRequest(SQLModel):
    commit_message: str | None = None
    label: str = Field(default="production", min_length=1)
    # None publishes the computed config (see `LangfusePublishDraft`).
    config_json: str | None = None
