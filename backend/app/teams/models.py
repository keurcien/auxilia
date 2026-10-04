from uuid import UUID

from sqlmodel import Field, UniqueConstraint

from app.models import BaseDBModel


class TeamDB(BaseDBModel, table=True):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_team_workspace_name"),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    name: str = Field(max_length=255, index=True, nullable=False)
    color: str | None = Field(default=None, max_length=7, nullable=True)
