from uuid import UUID

from sqlalchemy import Boolean, Column, String, Text, UniqueConstraint
from sqlmodel import Field

from app.models import BaseDBModel


class AgentSlackBotDB(BaseDBModel, table=True):
    """One independently installed Slack bot representing one agent."""

    __tablename__ = "agent_slack_bots"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_slack_bot_agent"),
        UniqueConstraint(
            "slack_team_id",
            "bot_user_id",
            name="uq_agent_slack_bot_installation",
        ),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id", ondelete="CASCADE", nullable=False, index=True
    )
    agent_id: UUID = Field(
        foreign_key="agents.id", ondelete="CASCADE", nullable=False, index=True
    )
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    require_mention_in_threads: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    show_tool_callouts: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    bot_token_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    signing_secret_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    slack_team_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    slack_team_name: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    bot_user_id: str = Field(sa_column=Column(String(64), nullable=False))
    bot_name: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )


class SlackThreadBindingDB(BaseDBModel, table=True):
    """Maps Slack's external thread coordinates to an internal Auxilia thread."""

    __tablename__ = "slack_thread_bindings"
    __table_args__ = (
        UniqueConstraint(
            "slack_bot_id",
            "channel_id",
            "slack_thread_ts",
            name="uq_slack_thread_external",
        ),
        UniqueConstraint("thread_id", name="uq_slack_thread_internal"),
    )

    slack_bot_id: UUID = Field(
        foreign_key="agent_slack_bots.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    thread_id: str = Field(
        foreign_key="threads.id", ondelete="CASCADE", nullable=False, index=True
    )
    channel_id: str = Field(max_length=64, nullable=False)
    slack_thread_ts: str = Field(max_length=64, nullable=False)
    slack_user_id: str = Field(max_length=64, nullable=False)
