from __future__ import annotations

import builtins
import unicodedata
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StaleRevisionError,
)
from app.projects.models import ProjectContextFileDB, ProjectDB, ProjectFolderDB
from app.projects.repository import ProjectRepository
from app.projects.runtime import PROJECT_CONTEXT_ROOT, context_file_description
from app.projects.schemas import (
    ProjectConfigResponse,
    ProjectConfigUpdate,
    ProjectContextFileCreate,
    ProjectContextFileResponse,
    ProjectContextFileSummary,
    ProjectContextFileUpdate,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectFolderCreate,
    ProjectFolderPatch,
    ProjectFolderResponse,
    ProjectFolderSearchResponse,
    ProjectPatch,
    ProjectResponse,
    ProjectSkillsResponse,
    ProjectSkillsUpdate,
    ProjectThreadRow,
    ProjectTreeResponse,
    ProjectTriggerRow,
)
from app.realtime.schemas import WorkspaceEventKind
from app.realtime.service import stage_workspace_event
from app.service import BaseService
from app.skills.models import SkillDB
from app.skills.repository import SkillRepository
from app.teams.repository import TeamRepository
from app.triggers.models import TriggerDB
from app.users.models import UserDB, WorkspaceRole
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id


MAX_CONTEXT_FILE_BYTES = 100_000
MAX_PROJECT_CONTEXT_BYTES = 500_000
MAX_PROJECT_CONTEXT_FILES = 100


def _validate_context_path(path: str) -> str:
    if (
        not path
        or path != path.strip()
        or path.startswith(("/", "\\"))
        or "\\" in path
        or any(unicodedata.category(character) == "Cc" for character in path)
    ):
        raise DomainValidationError("Context file path must be a safe relative path")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DomainValidationError("Context file path must be normalized")
    if any(len(part.encode("utf-8")) > 255 for part in parts):
        raise DomainValidationError(
            "Each context file path component must be at most 255 bytes"
        )
    normalized = PurePosixPath(path).as_posix()
    if normalized != path or PurePosixPath(path).suffix != ".md":
        raise DomainValidationError(
            "Context file path must be normalized and end in .md"
        )
    return normalized


def _context_size(content: str) -> int:
    return len(content.encode("utf-8"))


def _context_entry_size(path: str, content: str) -> int:
    absolute_path = f"{PROJECT_CONTEXT_ROOT}/{path}"
    description = context_file_description(content)
    index_line = (
        f"- `{absolute_path}`"
        + (f": {description}" if description is not None else "")
        + "\n"
    )
    return (
        _context_size(content)
        + len(absolute_path.encode("utf-8"))
        + len(index_line.encode("utf-8"))
    )


class ProjectService(BaseService[ProjectDB, ProjectRepository]):
    not_found_message = "Project not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(db, ProjectRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.teams = TeamRepository(db)

    @staticmethod
    def _can_manage(project: ProjectDB, user: UserDB) -> bool:
        return project.owner_id == user.id or user.role == WorkspaceRole.admin

    def _ensure_can_manage(self, project: ProjectDB, user: UserDB) -> None:
        if not self._can_manage(project, user):
            raise PermissionDeniedError("Not authorized to manage this project")

    async def _team_ids(self, project: ProjectDB) -> list[UUID]:
        if project.visibility != ResourceVisibility.teams:
            return []
        return await self.repository.list_team_ids(project.id)

    async def ensure_visible(self, project: ProjectDB, user: UserDB) -> None:
        if not is_resource_visible(
            visibility=project.visibility,
            owner_id=project.owner_id,
            team_ids=set(await self._team_ids(project)),
            user=user,
        ):
            raise NotFoundError(self.not_found_message)

    async def get_visible(
        self, project_id: UUID, user: UserDB, *, for_update: bool = False
    ) -> ProjectDB:
        project = (
            await self.repository.get_for_update(project_id)
            if for_update
            else await self.repository.get(project_id)
        )
        if project is None:
            raise NotFoundError(self.not_found_message)
        await self.ensure_visible(project, user)
        return project

    async def validate_placement(
        self,
        project_id: UUID | None,
        folder_id: UUID | None,
        user: UserDB,
        *,
        lock_project: bool = False,
    ) -> tuple[ProjectDB | None, ProjectFolderDB | None]:
        if project_id is None:
            if folder_id is not None:
                raise DomainValidationError("A folder requires a project")
            return None, None
        project = await self.get_visible(project_id, user, for_update=lock_project)
        folder = None
        if folder_id is not None:
            folder = (
                await self.repository.get_folder_for_update(folder_id)
                if lock_project
                else await self.repository.get_folder(folder_id)
            )
            if folder is None or folder.project_id != project.id:
                raise DomainValidationError(
                    "Folder must belong to the selected project"
                )
        return project, folder

    async def _validate_team_ids(self, team_ids: list[UUID]) -> None:
        for team_id in set(team_ids):
            if (
                await self.teams.get_in_workspace_for_key_share(
                    team_id, self.workspace_id
                )
                is None
            ):
                raise NotFoundError("Team not found")

    async def _response(
        self,
        project: ProjectDB,
        user: UserDB,
        team_ids: list[UUID] | None = None,
    ) -> ProjectResponse:
        return ProjectResponse.model_validate(
            project,
            update={
                "team_ids": team_ids
                if team_ids is not None
                else await self._team_ids(project),
                "can_manage": self._can_manage(project, user),
            },
        )

    @staticmethod
    def _context_summary(row: ProjectContextFileDB) -> ProjectContextFileSummary:
        return ProjectContextFileSummary.model_validate(
            row,
            update={
                "description": context_file_description(row.content),
                "size": _context_size(row.content),
            },
        )

    @classmethod
    def _context_response(cls, row: ProjectContextFileDB) -> ProjectContextFileResponse:
        return ProjectContextFileResponse.model_validate(
            row,
            update={
                "description": context_file_description(row.content),
                "size": _context_size(row.content),
            },
        )

    async def _tree_response(
        self, project: ProjectResponse, user: UserDB
    ) -> ProjectTreeResponse:
        folders = await self.repository.list_folders(project.id)
        threads = await self.repository.list_threads(project.id)
        triggers = await self.repository.list_triggers(project.id)
        return ProjectTreeResponse(
            **project.model_dump(),
            folders=[
                ProjectFolderResponse.model_validate(folder) for folder in folders
            ],
            threads=[
                ProjectThreadRow(
                    id=thread.id,
                    agent_id=thread.agent_id,
                    title=thread.first_message_content,
                    source=thread.source,
                    completed_at=thread.completed_at,
                    folder_id=thread.folder_id,
                    can_manage=thread.user_id == user.id,
                    created_at=thread.created_at,
                )
                for thread in threads
            ],
            triggers=[
                ProjectTriggerRow.model_validate(
                    trigger,
                    update={
                        "can_manage": trigger.owner_id == user.id
                        or user.role == WorkspaceRole.admin
                    },
                )
                for trigger in triggers
            ],
        )

    async def list(
        self,
        user: UserDB,
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[ProjectResponse]:
        projects = await self.repository.list_all()
        team_ids = await self.repository.list_team_ids_for_projects(
            [
                project.id
                for project in projects
                if project.visibility == ResourceVisibility.teams
            ]
        )
        visible = [
            project
            for project in projects
            if is_resource_visible(
                visibility=project.visibility,
                owner_id=project.owner_id,
                team_ids=set(team_ids.get(project.id, [])),
                user=user,
            )
        ]
        responses = [
            await self._response(project, user, team_ids.get(project.id, []))
            for project in visible
        ]
        if query:
            needle = query.casefold()
            responses = [
                project
                for project in responses
                if needle in project.name.casefold()
                or needle in project.description.casefold()
            ]
        return responses[:limit] if limit is not None else responses

    async def search_folders(
        self,
        project_id: UUID,
        user: UserDB,
        *,
        query: str = "",
        limit: int = 20,
    ) -> builtins.list[ProjectFolderSearchResponse]:
        project = await self.get_visible(project_id, user)
        folders = await self.repository.list_folders(project.id)
        by_id = {folder.id: folder for folder in folders}

        def folder_path(folder: ProjectFolderDB) -> str:
            names: builtins.list[str] = []
            seen: set[UUID] = set()
            current: ProjectFolderDB | None = folder
            while current is not None and current.id not in seen:
                seen.add(current.id)
                names.append(current.name)
                current = (
                    by_id.get(current.parent_id)
                    if current.parent_id is not None
                    else None
                )
            return " / ".join(reversed(names))

        needle = query.casefold().strip()
        options = [
            ProjectFolderSearchResponse(
                id=folder.id,
                name=folder.name,
                path=folder_path(folder),
            )
            for folder in folders
        ]
        if needle:
            options = [option for option in options if needle in option.path.casefold()]
        options.sort(key=lambda option: (option.path.casefold(), option.id))
        return options[:limit]

    async def tree(self, user: UserDB) -> builtins.list[ProjectTreeResponse]:
        projects = await self.list(user)
        return [await self._tree_response(project, user) for project in projects]

    async def get(self, project_id: UUID, user: UserDB) -> ProjectResponse:
        project = await self.get_visible(project_id, user)
        return await self._response(project, user)

    async def get_tree(self, project_id: UUID, user: UserDB) -> ProjectTreeResponse:
        project = await self.get_visible(project_id, user)
        return await self._tree_response(await self._response(project, user), user)

    async def detail(self, project_id: UUID, user: UserDB) -> ProjectDetailResponse:
        project = await self.get_visible(project_id, user)
        tree = await self._tree_response(await self._response(project, user), user)
        context_files = await self.repository.list_context_files(project.id)
        return ProjectDetailResponse(
            **tree.model_dump(),
            system_prompt=project.system_prompt,
            revision=project.revision,
            context_files=[self._context_summary(row) for row in context_files],
            skill_ids=await self.repository.list_skill_ids(project.id),
        )

    async def create(self, data: ProjectCreate, owner: UserDB) -> ProjectResponse:
        await self._validate_team_ids(data.team_ids)
        validate_visibility(data.visibility, data.team_ids)
        project = ProjectDB(
            workspace_id=self.workspace_id,
            owner_id=owner.id,
            name=data.name,
            emoji=data.emoji,
            description=data.description,
            visibility=data.visibility,
        )
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        if data.team_ids:
            await self.repository.set_team_ids(project.id, data.team_ids)
        await self._stage_events()
        return await self._response(project, owner, data.team_ids)

    async def _ensure_trigger_agents_fit(
        self,
        project: ProjectDB,
        visibility: ResourceVisibility,
        team_ids: builtins.list[UUID],
    ) -> None:
        agents = AgentRepository(self.db, self.workspace_id)
        for trigger in await self.repository.list_triggers(project.id):
            await self.ensure_trigger_agent_fits(
                trigger,
                visibility=visibility,
                owner_id=project.owner_id,
                team_ids=team_ids,
                agents=agents,
            )

    async def _ensure_bound_skills_fit(
        self,
        project: ProjectDB,
        visibility: ResourceVisibility,
        team_ids: builtins.list[UUID],
    ) -> None:
        skills = SkillRepository(self.db, self.workspace_id)
        for skill in await self.repository.list_skills(project.id, for_update=True):
            skill_team_ids = (
                set(await skills.list_team_ids(skill.id))
                if skill.visibility == ResourceVisibility.teams
                else set()
            )
            if not audience_contains(
                parent_visibility=visibility,
                parent_owner_id=project.owner_id,
                parent_team_ids=set(team_ids),
                child_visibility=skill.visibility,
                child_owner_id=skill.owner_id,
                child_team_ids=skill_team_ids,
            ):
                raise DomainValidationError(
                    f"Skill '{skill.name}' is more private than this project"
                )

    async def ensure_projects_fit_skill(
        self,
        skill: SkillDB,
        visibility: ResourceVisibility,
        team_ids: builtins.list[UUID],
    ) -> None:
        for project in await self.repository.list_projects_for_skill(skill.id):
            project_team_ids = (
                set(await self.repository.list_team_ids(project.id))
                if project.visibility == ResourceVisibility.teams
                else set()
            )
            if not audience_contains(
                parent_visibility=project.visibility,
                parent_owner_id=project.owner_id,
                parent_team_ids=project_team_ids,
                child_visibility=visibility,
                child_owner_id=skill.owner_id,
                child_team_ids=set(team_ids),
            ):
                raise DomainValidationError(
                    f"Skill scope is incompatible with project '{project.name}'"
                )

    async def ensure_trigger_agent_fits(
        self,
        trigger: TriggerDB,
        *,
        visibility: ResourceVisibility,
        owner_id: UUID,
        team_ids: builtins.list[UUID],
        agents: AgentRepository | None = None,
    ) -> None:
        agents = agents or AgentRepository(self.db, self.workspace_id)
        agent = await agents.get_scoped_for_update(trigger.agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        agent_team_ids = (
            set(await agents.get_team_ids(agent.id))
            if agent.visibility == ResourceVisibility.teams
            else set()
        )
        if not audience_contains(
            parent_visibility=visibility,
            parent_owner_id=owner_id,
            parent_team_ids=set(team_ids),
            child_visibility=agent.visibility,
            child_owner_id=agent.owner_id,
            child_team_ids=agent_team_ids,
        ):
            raise DomainValidationError(
                f"Agent '{agent.name}' is more private than this project"
            )

    async def update(
        self, project_id: UUID, data: ProjectPatch, user: UserDB
    ) -> ProjectResponse:
        project = await self.repository.get_for_update(project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        previous_visibility = project.visibility
        previous_team_ids = await self._team_ids(project)
        visibility = data.visibility or project.visibility
        team_ids = data.team_ids if data.team_ids is not None else previous_team_ids
        await self._validate_team_ids(team_ids)
        validate_visibility(visibility, team_ids)
        audience_changed = visibility != previous_visibility or set(team_ids) != set(
            previous_team_ids
        )
        if audience_changed:
            await self._ensure_trigger_agents_fit(project, visibility, team_ids)
            await self._ensure_bound_skills_fit(project, visibility, team_ids)
        project = await self.repository.update(project, data)
        if data.team_ids is not None or visibility != previous_visibility:
            await self.repository.set_team_ids(project.id, team_ids)
        await self._stage_events(content=audience_changed)
        return await self._response(project, user, team_ids)

    async def update_config(
        self, project_id: UUID, data: ProjectConfigUpdate, user: UserDB
    ) -> ProjectConfigResponse:
        project = await self.repository.get_for_update(project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        if data.revision != project.revision:
            raise StaleRevisionError(
                "This project changed since you opened it. Reload it before saving."
            )
        project.system_prompt = data.system_prompt
        project.revision += 1
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        await self._stage_events()
        return ProjectConfigResponse.model_validate(project)

    async def list_context_files(
        self, project_id: UUID, user: UserDB
    ) -> builtins.list[ProjectContextFileSummary]:
        project = await self.get_visible(project_id, user)
        return [
            self._context_summary(row)
            for row in await self.repository.list_context_files(project.id)
        ]

    async def get_context_file(
        self, file_id: UUID, user: UserDB
    ) -> ProjectContextFileResponse:
        row = await self.repository.get_context_file(file_id)
        if row is None:
            raise NotFoundError("Project context file not found")
        project = await self.get_visible(row.project_id, user)
        if project.id != row.project_id:
            raise NotFoundError("Project context file not found")
        return self._context_response(row)

    @staticmethod
    def _ensure_file_size(content: str) -> None:
        if _context_size(content) > MAX_CONTEXT_FILE_BYTES:
            raise DomainValidationError(
                f"Project context files can contain at most "
                f"{MAX_CONTEXT_FILE_BYTES:,} bytes"
            )

    async def _ensure_aggregate_size(
        self,
        project_id: UUID,
        path: str,
        content: str,
        *,
        replacing_file_id: UUID | None = None,
    ) -> None:
        rows = await self.repository.list_context_files(project_id)
        if replacing_file_id is None and len(rows) >= MAX_PROJECT_CONTEXT_FILES:
            raise DomainValidationError(
                f"A project can contain at most {MAX_PROJECT_CONTEXT_FILES} "
                "context files"
            )
        total = _context_entry_size(path, content)
        for row in rows:
            if row.id != replacing_file_id:
                total += _context_entry_size(row.path, row.content)
        if total > MAX_PROJECT_CONTEXT_BYTES:
            raise DomainValidationError(
                f"Project context can contain at most "
                f"{MAX_PROJECT_CONTEXT_BYTES:,} bytes in total"
            )

    async def create_context_file(
        self,
        project_id: UUID,
        data: ProjectContextFileCreate,
        user: UserDB,
    ) -> ProjectContextFileResponse:
        project = await self.repository.get_for_update(project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        path = _validate_context_path(data.path)
        self._ensure_file_size(data.content)
        await self._ensure_aggregate_size(project.id, path, data.content)
        try:
            row = await self.repository.create_context_file(
                project.id, path, data.content
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A project context file already uses this path"
            ) from exc
        await self._stage_events()
        return self._context_response(row)

    async def update_context_file(
        self,
        file_id: UUID,
        data: ProjectContextFileUpdate,
        user: UserDB,
    ) -> ProjectContextFileResponse:
        existing = await self.repository.get_context_file(file_id)
        if existing is None:
            raise NotFoundError("Project context file not found")
        project = await self.repository.get_for_update(existing.project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        row = await self.repository.get_context_file(file_id, for_update=True)
        if row is None or row.project_id != project.id:
            raise NotFoundError("Project context file not found")
        if data.revision != row.revision:
            raise StaleRevisionError(
                "This context file changed since you opened it. "
                "Reload it before saving."
            )
        path = _validate_context_path(data.path)
        self._ensure_file_size(data.content)
        await self._ensure_aggregate_size(
            project.id,
            path,
            data.content,
            replacing_file_id=row.id,
        )
        try:
            row = await self.repository.update_context_file(
                row, path=path, content=data.content
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A project context file already uses this path"
            ) from exc
        await self._stage_events()
        return self._context_response(row)

    async def delete_context_file(
        self, file_id: UUID, revision: int, user: UserDB
    ) -> None:
        existing = await self.repository.get_context_file(file_id)
        if existing is None:
            raise NotFoundError("Project context file not found")
        project = await self.repository.get_for_update(existing.project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        row = await self.repository.get_context_file(file_id, for_update=True)
        if row is None or row.project_id != project.id:
            raise NotFoundError("Project context file not found")
        if revision != row.revision:
            raise StaleRevisionError(
                "This context file changed since you opened it. "
                "Reload it before deleting."
            )
        await self.repository.delete_context_file(row)
        await self._stage_events()

    async def list_skills(
        self, project_id: UUID, user: UserDB
    ) -> ProjectSkillsResponse:
        project = await self.get_visible(project_id, user)
        return ProjectSkillsResponse(
            skill_ids=await self.repository.list_skill_ids(project.id),
            revision=project.revision,
        )

    async def set_skills(
        self,
        project_id: UUID,
        data: ProjectSkillsUpdate,
        user: UserDB,
    ) -> ProjectSkillsResponse:
        project = await self.repository.get_for_update(project_id)
        if project is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_can_manage(project, user)
        if data.revision != project.revision:
            raise StaleRevisionError(
                "This project changed since you opened it. Reload it before saving."
            )
        skill_ids = list(dict.fromkeys(data.skill_ids))
        project_team_ids = await self._team_ids(project)
        skills = SkillRepository(self.db, self.workspace_id)
        for skill_id in sorted(skill_ids, key=str):
            skill = await skills.get_for_update(skill_id)
            if skill is None:
                raise NotFoundError("Skill not found")
            skill_team_ids = (
                set(await skills.list_team_ids(skill.id))
                if skill.visibility == ResourceVisibility.teams
                else set()
            )
            if not audience_contains(
                parent_visibility=project.visibility,
                parent_owner_id=project.owner_id,
                parent_team_ids=set(project_team_ids),
                child_visibility=skill.visibility,
                child_owner_id=skill.owner_id,
                child_team_ids=skill_team_ids,
            ):
                raise DomainValidationError(
                    f"Skill '{skill.name}' is more private than this project"
                )
        changed = set(skill_ids) != set(
            await self.repository.list_skill_ids(project.id)
        )
        if changed:
            await self.repository.set_skill_ids(project.id, skill_ids)
        project.revision += 1
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        await self._stage_events()
        if changed:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.skills,
            )
        return ProjectSkillsResponse(
            skill_ids=skill_ids,
            revision=project.revision,
        )

    async def delete(self, project_id: UUID, user: UserDB) -> None:
        project = await self.get_or_404(project_id)
        self._ensure_can_manage(project, user)
        had_skills = bool(await self.repository.list_skill_ids(project.id))
        await self.repository.detach_project_content(project.id)
        await self.repository.delete(project)
        await self._stage_events(content=True)
        if had_skills:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.skills,
            )

    async def create_folder(
        self, project_id: UUID, data: ProjectFolderCreate, user: UserDB
    ) -> ProjectFolderResponse:
        project = await self.get_or_404(project_id)
        self._ensure_can_manage(project, user)
        await self._validate_parent(project.id, data.parent_id)
        try:
            folder = await self.repository.create_folder(
                project.id, data.name, data.parent_id
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A folder with this name already exists at this level"
            ) from exc
        await self._stage_events()
        return ProjectFolderResponse.model_validate(folder)

    async def update_folder(
        self, folder_id: UUID, data: ProjectFolderPatch, user: UserDB
    ) -> ProjectFolderResponse:
        folder = await self.repository.get_folder_for_update(folder_id)
        if folder is None:
            raise NotFoundError("Folder not found")
        project = await self.get_or_404(folder.project_id)
        self._ensure_can_manage(project, user)
        if "parent_id" in data.model_fields_set:
            await self._validate_parent(project.id, data.parent_id, folder.id)
        try:
            folder = await self.repository.update_folder(folder, data)
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A folder with this name already exists at this level"
            ) from exc
        await self._stage_events()
        return ProjectFolderResponse.model_validate(folder)

    async def delete_folder(self, folder_id: UUID, user: UserDB) -> None:
        folder = await self.repository.get_folder(folder_id)
        if folder is None:
            raise NotFoundError("Folder not found")
        project = await self.get_or_404(folder.project_id)
        self._ensure_can_manage(project, user)
        await self.repository.lock_triggers_for_folder(folder.id)
        folder = await self.repository.get_folder_for_update(folder.id)
        if folder is None:
            raise NotFoundError("Folder not found")
        if await self.repository.has_reparent_conflict(folder):
            raise DomainValidationError(
                "Folder cannot be deleted because a child name already exists "
                "at the parent level"
            )
        try:
            await self.repository.reparent_and_delete_folder(folder)
        except IntegrityError as exc:
            raise DomainValidationError(
                "Folder cannot be deleted because its children conflict "
                "at the parent level"
            ) from exc
        await self._stage_events(content=True)

    async def _validate_parent(
        self,
        project_id: UUID,
        parent_id: UUID | None,
        folder_id: UUID | None = None,
    ) -> None:
        if parent_id is None:
            return
        if parent_id == folder_id:
            raise DomainValidationError("A folder cannot be its own parent")
        parent = await self.repository.get_folder_for_update(parent_id)
        if parent is None or parent.project_id != project_id:
            raise DomainValidationError("Parent folder must belong to the project")
        seen: set[UUID] = set()
        current = parent
        while current.parent_id is not None:
            if current.id in seen or current.parent_id == folder_id:
                raise DomainValidationError("Folder ancestry cannot contain a cycle")
            seen.add(current.id)
            ancestor = await self.repository.get_folder_for_update(current.parent_id)
            if ancestor is None or ancestor.project_id != project_id:
                raise DomainValidationError("Folder ancestry is invalid")
            current = ancestor

    async def _stage_events(self, *, content: bool = False) -> None:
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.projects,
        )
        if content:
            for kind in (WorkspaceEventKind.threads, WorkspaceEventKind.triggers):
                await stage_workspace_event(
                    self.db,
                    workspace_id=self.workspace_id,
                    kind=kind,
                )


def get_project_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> ProjectService:
    return ProjectService(db, workspace_id)
