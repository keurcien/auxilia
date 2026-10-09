import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.database import get_db
from app.exceptions import AlreadyExistsError, NotFoundError
from app.invites.models import InviteCreateDB, InviteDB, InviteStatus
from app.invites.repository import InviteRepository
from app.invites.schemas import InviteResponse
from app.service import BaseService
from app.teams.repository import TeamRepository
from app.users.models import UserDB
from app.workspaces.repository import WorkspaceRepository


class InviteService(BaseService[InviteDB, InviteRepository]):
    not_found_message = "Invite not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, InviteRepository(db))

    def build_invite_url(self, token: str) -> str:
        return f"{auth_settings.FRONTEND_URL}/invite/{token}"

    def _to_response(
        self,
        invite: InviteDB,
        include_url: bool = False,
        invited_by_name: str | None = None,
    ) -> InviteResponse:
        return InviteResponse(
            id=invite.id,
            workspace_id=invite.workspace_id,
            email=invite.email,
            role=invite.role,
            status=invite.status.value,
            invite_url=self.build_invite_url(invite.token) if include_url else None,
            invited_by=invite.invited_by,
            invited_by_name=invited_by_name,
            team_id=invite.team_id,
            expires_at=invite.expires_at,
            created_at=invite.created_at,
        )

    @staticmethod
    def _is_usable(invite: InviteDB | None) -> bool:
        return (
            invite is not None
            and invite.status == InviteStatus.pending
            and invite.expires_at >= datetime.now(UTC)
        )

    async def create(
        self,
        email: str,
        role: str,
        invited_by: UUID,
        workspace_id: UUID,
        team_id: UUID | None = None,
    ) -> InviteDB:
        """Create a new invite, revoking any existing pending invite for the same email."""
        result = await self.db.execute(select(UserDB).where(UserDB.email == email))
        existing_user = result.scalar_one_or_none()
        if existing_user and await WorkspaceRepository(self.db).get_membership(
            workspace_id, existing_user.id
        ):
            raise AlreadyExistsError("User is already a workspace member")
        if team_id is not None and not await TeamRepository(
            self.db
        ).get_in_workspace_for_key_share(team_id, workspace_id):
            raise NotFoundError("Team not found")
        await self.repository.revoke_pending_by_email(workspace_id, email)
        data = InviteCreateDB(
            workspace_id=workspace_id,
            email=email,
            role=role,
            token=secrets.token_urlsafe(32),
            invited_by=invited_by,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            team_id=team_id,
        )
        return await self.repository.create(data)

    async def get_by_token(self, token: str) -> InviteDB | None:
        invite = await self.repository.get_by_token(token)
        return invite if self._is_usable(invite) else None

    async def get_pending_by_email(
        self, email: str, workspace_id: UUID | None = None
    ) -> InviteDB | None:
        invite = await self.repository.get_pending_by_email(email, workspace_id)
        return invite if self._is_usable(invite) else None

    async def list_pending_with_inviters(
        self, workspace_id: UUID
    ) -> list[tuple[InviteDB, str | None]]:
        invites = await self.repository.list_pending(workspace_id)
        inviter_ids = list({inv.invited_by for inv in invites})
        if not inviter_ids:
            return [(inv, None) for inv in invites]
        users_result = await self.db.execute(
            select(UserDB).where(UserDB.id.in_(inviter_ids))
        )
        inviters = {user.id: user.name for user in users_result.scalars().all()}
        return [(inv, inviters.get(inv.invited_by)) for inv in invites]

    async def revoke(self, invite_id: UUID, workspace_id: UUID) -> InviteDB | None:
        invite = await self.repository.get(invite_id)
        if invite is None or invite.workspace_id != workspace_id:
            return None
        return await self.repository.set_status(invite, InviteStatus.revoked)


def get_invite_service(db: AsyncSession = Depends(get_db)) -> InviteService:
    return InviteService(db)
