from uuid import UUID

from sqlalchemy import Enum as SAEnum, Text
from sqlmodel import Column, Field, SQLModel, UniqueConstraint

from app.models import BaseDBModel, TimestampMixin
from app.visibility import ResourceVisibility


class ProjectBase(SQLModel):
    name: str = Field(min_length=1, max_length=255, nullable=False)
    description: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )


class ProjectDB(ProjectBase, BaseDBModel, table=True):
    __tablename__ = "projects"

    workspace_id: UUID = Field(
        foreign_key="workspaces.id", ondelete="CASCADE", nullable=False, index=True
    )
    owner_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    visibility: ResourceVisibility = Field(
        default=ResourceVisibility.personal,
        sa_column=Column(
            SAEnum(ResourceVisibility, native_enum=False, create_constraint=False),
            nullable=False,
            server_default=ResourceVisibility.personal.value,
        ),
    )
    system_prompt: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )
    revision: int = Field(default=1, nullable=False)


class ProjectTeamDB(TimestampMixin, SQLModel, table=True):
    __tablename__ = "project_teams"

    project_id: UUID = Field(
        foreign_key="projects.id",
        ondelete="CASCADE",
        nullable=False,
        primary_key=True,
    )
    team_id: UUID = Field(
        foreign_key="teams.id",
        ondelete="CASCADE",
        nullable=False,
        primary_key=True,
        index=True,
    )


class ProjectFolderDB(BaseDBModel, table=True):
    __tablename__ = "project_folders"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "parent_id",
            "name",
            name="uq_project_folder_sibling_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

    project_id: UUID = Field(
        foreign_key="projects.id", ondelete="CASCADE", nullable=False, index=True
    )
    parent_id: UUID | None = Field(
        default=None,
        foreign_key="project_folders.id",
        ondelete="SET NULL",
        nullable=True,
        index=True,
    )
    name: str = Field(min_length=1, max_length=255, nullable=False)


class ProjectContextFileDB(BaseDBModel, table=True):
    __tablename__ = "project_context_files"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "path",
            name="uq_project_context_file_path",
        ),
    )

    project_id: UUID = Field(
        foreign_key="projects.id", ondelete="CASCADE", nullable=False, index=True
    )
    path: str = Field(max_length=500, nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    revision: int = Field(default=1, nullable=False)


class ProjectSkillDB(TimestampMixin, SQLModel, table=True):
    __tablename__ = "project_skills"

    project_id: UUID = Field(
        foreign_key="projects.id",
        ondelete="CASCADE",
        nullable=False,
        primary_key=True,
    )
    skill_id: UUID = Field(
        foreign_key="skills.id",
        ondelete="CASCADE",
        nullable=False,
        primary_key=True,
        index=True,
    )
