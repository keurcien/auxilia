from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models import BaseDBModel


class SlackNotificationSettingsDB(BaseDBModel, table=True):
    __tablename__ = "slack_notification_settings"
    __table_args__ = (
        CheckConstraint(
            "(bot_token_encrypted IS NULL) = (signing_secret_encrypted IS NULL)",
            name="ck_slack_notification_credentials_pair",
        ),
        UniqueConstraint(
            "workspace_id", "key", name="uq_slack_notifications_workspace_key"
        ),
    )

    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    slack_team_id: str | None = Field(default=None, unique=True, index=True)
    key: str = Field(default="default", nullable=False)
    enabled: bool = Field(default=False, nullable=False)
    bot_token_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    signing_secret_encrypted: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
