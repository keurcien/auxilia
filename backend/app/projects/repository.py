from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, col, select

from app.projects.models import (
    ProjectContextFileDB,
    ProjectDB,
    ProjectFolderDB,
    ProjectSkillDB,
    ProjectTeamDB,
)
from app.repository import BaseRepository
from app.skills.models import SkillDB
from app.threads.models import ThreadDB
from app.triggers.models import TriggerDB


class ProjectRepository(BaseRepository[ProjectDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(ProjectDB, db)
        self.workspace_id = workspace_id

    async def get(self, project_id: UUID | str) -> ProjectDB | None:
        stmt = select(ProjectDB).where(
            col(ProjectDB.id) == project_id,
            col(ProjectDB.workspace_id) == self.workspace_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(self, project_id: UUID) -> ProjectDB | None:
        stmt = (
            select(ProjectDB)
            .where(
                col(ProjectDB.id) == project_id,
                col(ProjectDB.workspace_id) == self.workspace_id,
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ProjectDB]:
        stmt = (
            select(ProjectDB)
            .where(col(ProjectDB.workspace_id) == self.workspace_id)
            .order_by(col(ProjectDB.name), col(ProjectDB.id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_team_ids(self, project_id: UUID) -> list[UUID]:
        stmt = select(ProjectTeamDB.team_id).where(
            col(ProjectTeamDB.project_id) == project_id
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_team_ids_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, list[UUID]]:
        if not project_ids:
            return {}
        stmt = select(ProjectTeamDB.project_id, ProjectTeamDB.team_id).where(
            col(ProjectTeamDB.project_id).in_(project_ids)
        )
        grouped: dict[UUID, list[UUID]] = {}
        for project_id, team_id in (await self.db.execute(stmt)).all():
            grouped.setdefault(project_id, []).append(team_id)
        return grouped

    async def set_team_ids(self, project_id: UUID, team_ids: list[UUID]) -> None:
        stmt = delete(ProjectTeamDB).where(col(ProjectTeamDB.project_id) == project_id)
        await self.db.execute(stmt)
        self.db.add_all(
            [
                ProjectTeamDB(project_id=project_id, team_id=team_id)
                for team_id in dict.fromkeys(team_ids)
            ]
        )
        await self.db.flush()

    async def list_context_files(self, project_id: UUID) -> list[ProjectContextFileDB]:
        stmt = (
            select(ProjectContextFileDB)
            .where(col(ProjectContextFileDB.project_id) == project_id)
            .order_by(col(ProjectContextFileDB.path), col(ProjectContextFileDB.id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_context_file(
        self, file_id: UUID, *, for_update: bool = False
    ) -> ProjectContextFileDB | None:
        stmt = (
            select(ProjectContextFileDB)
            .join(ProjectDB, col(ProjectContextFileDB.project_id) == col(ProjectDB.id))
            .where(
                col(ProjectContextFileDB.id) == file_id,
                col(ProjectDB.workspace_id) == self.workspace_id,
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_context_file(
        self, project_id: UUID, path: str, content: str
    ) -> ProjectContextFileDB:
        row = ProjectContextFileDB(
            project_id=project_id,
            path=path,
            content=content,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_context_file(
        self,
        row: ProjectContextFileDB,
        *,
        path: str,
        content: str,
    ) -> ProjectContextFileDB:
        row.path = path
        row.content = content
        row.revision += 1
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_context_file(self, row: ProjectContextFileDB) -> None:
        await self.db.delete(row)
        await self.db.flush()

    async def list_skill_ids(self, project_id: UUID) -> list[UUID]:
        stmt = (
            select(ProjectSkillDB.skill_id)
            .where(col(ProjectSkillDB.project_id) == project_id)
            .order_by(col(ProjectSkillDB.skill_id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_skills(
        self, project_id: UUID, *, for_update: bool = False
    ) -> list[SkillDB]:
        stmt = (
            select(SkillDB)
            .join(ProjectSkillDB, col(ProjectSkillDB.skill_id) == col(SkillDB.id))
            .where(
                col(ProjectSkillDB.project_id) == project_id,
                col(SkillDB.workspace_id) == self.workspace_id,
            )
            .order_by(col(SkillDB.id))
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_skill_ids(self, project_id: UUID, skill_ids: list[UUID]) -> None:
        stmt = delete(ProjectSkillDB).where(
            col(ProjectSkillDB.project_id) == project_id
        )
        await self.db.execute(stmt)
        self.db.add_all(
            [
                ProjectSkillDB(project_id=project_id, skill_id=skill_id)
                for skill_id in dict.fromkeys(skill_ids)
            ]
        )
        await self.db.flush()

    async def list_projects_for_skill(
        self, skill_id: UUID, *, for_update: bool = False
    ) -> list[ProjectDB]:
        stmt = (
            select(ProjectDB)
            .join(ProjectSkillDB, col(ProjectSkillDB.project_id) == col(ProjectDB.id))
            .where(
                col(ProjectSkillDB.skill_id) == skill_id,
                col(ProjectDB.workspace_id) == self.workspace_id,
            )
            .order_by(col(ProjectDB.id))
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_folder(self, folder_id: UUID) -> ProjectFolderDB | None:
        stmt = (
            select(ProjectFolderDB)
            .join(ProjectDB, col(ProjectFolderDB.project_id) == col(ProjectDB.id))
            .where(
                col(ProjectFolderDB.id) == folder_id,
                col(ProjectDB.workspace_id) == self.workspace_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_folder_for_update(self, folder_id: UUID) -> ProjectFolderDB | None:
        stmt = (
            select(ProjectFolderDB)
            .join(ProjectDB, col(ProjectFolderDB.project_id) == col(ProjectDB.id))
            .where(
                col(ProjectFolderDB.id) == folder_id,
                col(ProjectDB.workspace_id) == self.workspace_id,
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_folders(self, project_id: UUID) -> list[ProjectFolderDB]:
        stmt = (
            select(ProjectFolderDB)
            .where(col(ProjectFolderDB.project_id) == project_id)
            .order_by(col(ProjectFolderDB.name), col(ProjectFolderDB.id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_folder(
        self, project_id: UUID, name: str, parent_id: UUID | None
    ) -> ProjectFolderDB:
        folder = ProjectFolderDB(
            project_id=project_id,
            name=name,
            parent_id=parent_id,
        )
        self.db.add(folder)
        await self.db.flush()
        await self.db.refresh(folder)
        return folder

    async def update_folder(
        self, folder: ProjectFolderDB, data: SQLModel
    ) -> ProjectFolderDB:
        folder.sqlmodel_update(data.model_dump(exclude_unset=True))
        self.db.add(folder)
        await self.db.flush()
        await self.db.refresh(folder)
        return folder

    async def list_threads(self, project_id: UUID) -> list[ThreadDB]:
        stmt = (
            select(ThreadDB)
            .where(
                col(ThreadDB.workspace_id) == self.workspace_id,
                col(ThreadDB.project_id) == project_id,
            )
            .order_by(col(ThreadDB.created_at).desc(), col(ThreadDB.id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_triggers(self, project_id: UUID) -> list[TriggerDB]:
        stmt = (
            select(TriggerDB)
            .where(
                col(TriggerDB.workspace_id) == self.workspace_id,
                col(TriggerDB.project_id) == project_id,
            )
            .order_by(col(TriggerDB.created_at).desc(), col(TriggerDB.id))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def detach_project_content(self, project_id: UUID) -> None:
        await self.lock_triggers_for_project(project_id)
        thread_stmt = (
            update(ThreadDB)
            .where(
                col(ThreadDB.workspace_id) == self.workspace_id,
                col(ThreadDB.project_id) == project_id,
            )
            .values(project_id=None, folder_id=None)
        )
        trigger_stmt = (
            update(TriggerDB)
            .where(
                col(TriggerDB.workspace_id) == self.workspace_id,
                col(TriggerDB.project_id) == project_id,
            )
            .values(project_id=None, folder_id=None)
        )
        await self.db.execute(trigger_stmt)
        await self.db.execute(thread_stmt)

    async def lock_triggers_for_project(self, project_id: UUID) -> None:
        stmt = (
            select(TriggerDB.id)
            .where(
                col(TriggerDB.workspace_id) == self.workspace_id,
                col(TriggerDB.project_id) == project_id,
            )
            .order_by(col(TriggerDB.id))
            .with_for_update()
        )
        await self.db.execute(stmt)

    async def lock_triggers_for_folder(self, folder_id: UUID) -> None:
        stmt = (
            select(TriggerDB.id)
            .where(
                col(TriggerDB.workspace_id) == self.workspace_id,
                col(TriggerDB.folder_id) == folder_id,
            )
            .order_by(col(TriggerDB.id))
            .with_for_update()
        )
        await self.db.execute(stmt)

    async def reparent_and_delete_folder(self, folder: ProjectFolderDB) -> None:
        child_stmt = (
            update(ProjectFolderDB)
            .where(col(ProjectFolderDB.parent_id) == folder.id)
            .values(parent_id=folder.parent_id)
        )
        thread_stmt = (
            update(ThreadDB)
            .where(
                col(ThreadDB.project_id) == folder.project_id,
                col(ThreadDB.folder_id) == folder.id,
            )
            .values(folder_id=folder.parent_id)
        )
        trigger_stmt = (
            update(TriggerDB)
            .where(
                col(TriggerDB.project_id) == folder.project_id,
                col(TriggerDB.folder_id) == folder.id,
            )
            .values(folder_id=folder.parent_id)
        )
        await self.db.execute(trigger_stmt)
        await self.db.execute(child_stmt)
        await self.db.execute(thread_stmt)
        await self.db.delete(folder)
        await self.db.flush()

    async def has_reparent_conflict(self, folder: ProjectFolderDB) -> bool:
        child_names_stmt = select(ProjectFolderDB.name).where(
            col(ProjectFolderDB.parent_id) == folder.id
        )
        child_names = list((await self.db.execute(child_names_stmt)).scalars().all())
        if not child_names:
            return False
        parent_filter = (
            col(ProjectFolderDB.parent_id).is_(None)
            if folder.parent_id is None
            else col(ProjectFolderDB.parent_id) == folder.parent_id
        )
        conflict_stmt = select(ProjectFolderDB.id).where(
            col(ProjectFolderDB.project_id) == folder.project_id,
            parent_filter,
            col(ProjectFolderDB.id) != folder.id,
            col(ProjectFolderDB.name).in_(child_names),
        )
        return (await self.db.execute(conflict_stmt)).first() is not None
