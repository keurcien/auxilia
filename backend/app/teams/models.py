from sqlmodel import Field

from app.models import BaseDBModel


class TeamDB(BaseDBModel, table=True):
    __tablename__ = "teams"

    name: str = Field(max_length=255, unique=True, index=True, nullable=False)
    color: str | None = Field(default=None, max_length=7, nullable=True)
