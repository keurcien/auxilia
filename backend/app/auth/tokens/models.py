from uuid import UUID

from sqlmodel import Field

from app.models import BaseDBModel


class PersonalAccessTokenDB(BaseDBModel, table=True):
    __tablename__ = "personal_access_tokens"

    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(max_length=255, nullable=False)
    token_hash: str = Field(nullable=False)
    prefix: str = Field(max_length=12, nullable=False, index=True)
