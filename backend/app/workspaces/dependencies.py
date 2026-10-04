from collections.abc import Callable
from uuid import UUID

from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.exceptions import DomainValidationError, PermissionDeniedError
from app.users.models import UserDB
from app.workspaces.models import WorkspaceMembershipDB, WorkspaceRole


ROLE_HIERARCHY: dict[WorkspaceRole, int] = {
    WorkspaceRole.member: 0,
    WorkspaceRole.editor: 1,
    WorkspaceRole.admin: 2,
}


async def get_active_membership(
    current_user: UserDB = Depends(get_current_user),
) -> WorkspaceMembershipDB:
    if current_user.active_workspace_id is None:
        raise DomainValidationError("No active workspace selected")
    # Authentication already validated membership and hydrated these values.
    # Reconstructing the DTO avoids a second membership query on every route.
    return WorkspaceMembershipDB(
        workspace_id=current_user.active_workspace_id,
        user_id=current_user.id,
        role=current_user.role,
        team_id=current_user.team_id,
    )


async def get_active_workspace_id(
    membership: WorkspaceMembershipDB = Depends(get_active_membership),
) -> UUID:
    return membership.workspace_id


def require_workspace_role(minimum_role: WorkspaceRole) -> Callable:
    async def dependency(
        current_user: UserDB = Depends(get_current_user),
        membership: WorkspaceMembershipDB = Depends(get_active_membership),
    ) -> UserDB:
        if ROLE_HIERARCHY[membership.role] < ROLE_HIERARCHY[minimum_role]:
            raise PermissionDeniedError(f"{minimum_role.value} access required")
        return current_user

    return dependency
