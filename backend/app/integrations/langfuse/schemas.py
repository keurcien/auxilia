from datetime import datetime

from sqlmodel import SQLModel


class LangfuseStatusResponse(SQLModel):
    enabled: bool


class LangfusePromptVersion(SQLModel):
    version: int
    labels: list[str]
    commit_message: str | None = None
    text: str
    author: str | None = None
    created_at: datetime | None = None


class LangfusePromptResponse(SQLModel):
    """The agent's production prompt, and whether the instructions still match it."""

    production: LangfusePromptVersion | None
    diverged: bool


class LangfusePublishRequest(SQLModel):
    commit_message: str | None = None
