from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.service import BaseService
from app.users.models import UserDB
from app.utils.images import ProcessedImage
from app.workspaces.models import (
    WorkspaceDB,
    WorkspaceImageDB,
    WorkspaceMembershipDB,
    WorkspaceRole,
)
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceDelete,
    WorkspacePatch,
    WorkspaceResponse,
)


class WorkspaceService(BaseService[WorkspaceDB, WorkspaceRepository]):
    not_found_message = "Workspace not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, WorkspaceRepository(db))

    async def list_for_user(self, user_id: UUID) -> list[WorkspaceResponse]:
        rows = await self.repository.list_for_user(user_id)
        return [
            WorkspaceResponse.model_validate(
                workspace, update={"role": membership.role}
            )
            for workspace, membership in rows
        ]

    async def create(self, data: WorkspaceCreate, user: UserDB) -> WorkspaceDB:
        name = data.name.strip()
        if not name:
            raise DomainValidationError("Workspace name cannot be empty")
        if (
            not user.is_instance_owner
            and not user.can_create_workspace
            and await self.repository.get_first_membership(user.id) is not None
        ):
            raise PermissionDeniedError("Workspace creation is not allowed")
        workspace = await self.repository.create(
            WorkspaceCreate(name=name, emoji=data.emoji, color=data.color)
        )
        await self.repository.create_membership(
            WorkspaceMembershipDB(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.admin,
            )
        )
        return workspace

    async def update(
        self, workspace_id: UUID, user_id: UUID, data: WorkspacePatch
    ) -> WorkspaceResponse:
        await self.require_admin(workspace_id, user_id)
        workspace = await self.get_or_404(workspace_id)
        update_data = data.model_dump(exclude_unset=True)
        if "name" in update_data:
            name = update_data["name"]
            if name is None or not name.strip():
                raise DomainValidationError("Workspace name cannot be empty")
            update_data["name"] = name.strip()
        workspace = await self.repository.update(
            workspace, WorkspacePatch.model_validate(update_data)
        )
        return WorkspaceResponse.model_validate(
            workspace,
            update={"role": WorkspaceRole.admin},
        )

    async def get_image(self, workspace_id: UUID, user_id: UUID) -> WorkspaceImageDB:
        await self.require_membership(workspace_id, user_id)
        image = await self.repository.get_image(workspace_id)
        if image is None:
            raise NotFoundError("Workspace image not found")
        return image

    async def set_image(
        self, workspace_id: UUID, user_id: UUID, image: ProcessedImage
    ) -> UUID:
        await self.require_admin(workspace_id, user_id)
        revision = uuid4()
        await self.repository.set_image(
            workspace_id,
            data=image.data,
            media_type=image.media_type,
            sha256=image.sha256,
            revision=revision,
        )
        return revision

    async def delete_image(self, workspace_id: UUID, user_id: UUID) -> None:
        await self.require_admin(workspace_id, user_id)
        await self.repository.delete_image(workspace_id)

    async def delete_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        active_workspace_id: UUID | None,
        confirmation: WorkspaceDelete,
    ) -> UUID | None:
        await self.require_admin(workspace_id, user_id)
        workspace = await self.get_or_404(workspace_id)
        if confirmation.name != workspace.name:
            raise DomainValidationError("Workspace name confirmation does not match")

        next_workspace_id = active_workspace_id
        if active_workspace_id == workspace_id:
            next_membership = await self.repository.get_first_membership_except(
                user_id, workspace_id
            )
            next_workspace_id = (
                next_membership.workspace_id if next_membership is not None else None
            )

        await self.repository.delete(workspace)
        return next_workspace_id

    async def require_membership(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMembershipDB:
        membership = await self.repository.get_membership(workspace_id, user_id)
        if membership is None:
            raise PermissionDeniedError("Workspace access denied")
        return membership

    async def require_admin(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMembershipDB:
        membership = await self.require_membership(workspace_id, user_id)
        if membership.role != WorkspaceRole.admin:
            raise PermissionDeniedError("Admin access required")
        return membership


def get_workspace_service(
    db: AsyncSession = Depends(get_db),
) -> WorkspaceService:
    return WorkspaceService(db)
