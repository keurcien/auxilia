from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class PersonalAccessTokenCreate(SQLModel):
    name: str = Field(max_length=255)


class PersonalAccessTokenCreateDB(SQLModel):
    user_id: UUID
    name: str
    token_hash: str
    prefix: str


class PersonalAccessTokenResponse(SQLModel):
    id: UUID
    name: str
    prefix: str
    created_at: datetime


class PersonalAccessTokenCreatedResponse(PersonalAccessTokenResponse):
    """Returned only at creation time — includes the plaintext token."""

    token: str
