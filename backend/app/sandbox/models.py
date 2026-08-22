from enum import Enum

from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Enum as SAEnum, Field, SQLModel

from app.models import BaseDBModel


class SandboxProviderType(str, Enum):
    opensandbox = "opensandbox"
    cloudrun = "cloudrun"
    daytona = "daytona"


class SandboxBase(SQLModel):
    """Shared shape of every sandbox: endpoint + provider + extras.

    `url` and the credential are first-class (every provider has exactly one
    of each); `config` holds only the provider-specific remainder plus the
    shared runtime knobs (default_packages, timeout), always validated through
    the typed union in schemas.py before it touches the row.
    """

    name: str = Field(max_length=255, nullable=False)
    description: str | None = Field(default=None, max_length=255)
    provider: SandboxProviderType = Field(
        sa_column=Column(SAEnum(SandboxProviderType), nullable=False)
    )
    url: str = Field(nullable=False)
    config: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


class SandboxDB(SandboxBase, BaseDBModel, table=True):
    __tablename__ = "sandboxes"

    encrypted_secret: str | None = Field(default=None)
