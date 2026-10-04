from uuid import UUID

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field

from app.models import BaseDBModel


class InstanceAppearanceDB(BaseDBModel, table=True):
    __tablename__ = "instance_appearance"

    key: str = Field(default="default", nullable=False, unique=True)
    app_name: str = Field(default="auxilia", max_length=50, nullable=False)
    logo_data: bytes | None = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
    )
    logo_media_type: str | None = Field(default=None, max_length=50)
    logo_sha256: str | None = Field(default=None, max_length=64)
    logo_revision: UUID | None = Field(default=None, nullable=True)
