from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.threads.models import ThreadSource
from app.triggers.models import TriggerType
from app.visibility import ResourceVisibility


class ProjectCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    emoji: str | None = Field(default=None, max_length=10)
    description: str = Field(default="", max_length=4_000)
    visibility: ResourceVisibility = ResourceVisibility.personal
    team_ids: list[UUID] = Field(default_factory=list, exclude=True)


class ProjectPatch(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    emoji: str | None = Field(default=None, max_length=10)
    description: str | None = Field(default=None, max_length=4_000)
    visibility: ResourceVisibility | None = None
    team_ids: list[UUID] | None = Field(default=None, exclude=True)


class ProjectResponse(SQLModel):
    id: UUID
    workspace_id: UUID
    owner_id: UUID
    name: str
    emoji: str | None = None
    description: str
    visibility: ResourceVisibility
    team_ids: list[UUID] = Field(default_factory=list)
    can_manage: bool = False
    created_at: datetime
    updated_at: datetime


class ProjectConfigUpdate(SQLModel):
    system_prompt: str = Field(max_length=110_000)
    revision: int = Field(ge=1)


class ProjectConfigResponse(SQLModel):
    system_prompt: str
    revision: int
    updated_at: datetime


class ProjectContextFileCreate(SQLModel):
    path: str = Field(min_length=1, max_length=500)
    content: str


class ProjectContextFileUpdate(ProjectContextFileCreate):
    revision: int = Field(ge=1)


class ProjectContextFileSummary(SQLModel):
    id: UUID
    project_id: UUID
    path: str
    description: str | None = None
    size: int
    revision: int
    created_at: datetime
    updated_at: datetime


class ProjectContextFileResponse(ProjectContextFileSummary):
    content: str


class ProjectSkillsUpdate(SQLModel):
    skill_ids: list[UUID] = Field(default_factory=list)
    revision: int = Field(ge=1)


class ProjectSkillsResponse(SQLModel):
    skill_ids: list[UUID] = Field(default_factory=list)
    revision: int


class ProjectFolderCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None


class ProjectFolderPatch(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: UUID | None = None


class ProjectFolderResponse(SQLModel):
    id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectFolderSearchResponse(SQLModel):
    id: UUID
    name: str
    path: str


class ProjectThreadRow(SQLModel):
    id: str
    agent_id: UUID
    title: str | None = None
    source: ThreadSource
    completed_at: datetime | None = None
    folder_id: UUID | None = None
    can_manage: bool = False
    created_at: datetime


class ProjectTriggerRow(SQLModel):
    id: UUID
    name: str
    trigger_type: TriggerType
    folder_id: UUID | None = None
    is_active: bool
    can_manage: bool = False


class ProjectTreeResponse(ProjectResponse):
    folders: list[ProjectFolderResponse] = Field(default_factory=list)
    threads: list[ProjectThreadRow] = Field(default_factory=list)
    triggers: list[ProjectTriggerRow] = Field(default_factory=list)


class ProjectDetailResponse(ProjectTreeResponse):
    system_prompt: str
    revision: int
    context_files: list[ProjectContextFileSummary] = Field(default_factory=list)
    skill_ids: list[UUID] = Field(default_factory=list)
