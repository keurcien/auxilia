from sqlmodel import Field

from app.models import BaseDBModel


class TagDB(BaseDBModel, table=True):
    __tablename__ = "tags"

    name: str = Field(max_length=255, unique=True, index=True, nullable=False)
