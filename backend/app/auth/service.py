"""Authentication business logic.

Keeps ``auth/router.py`` thin by centralizing signup/signin/OAuth flows here.
Services return the freshly authenticated ``UserDB`` plus a JWT string; the
router is responsible for attaching the auth cookie to the response.
"""

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.auth.configuration import WorkspaceAuthenticationService
from app.auth.schemas import (
    InviteAcceptRequest,
    SigninRequest,
    SignupRequest,
    TwoFactorSigninVerifyRequest,
)
from app.auth.two_factor import create_scoped_token, decode_scoped_token
from app.auth.two_factor_challenges import consume_challenge, record_challenge_attempt
from app.auth.utils import create_access_token, get_password_hash, verify_password
from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainError,
    DomainValidationError,
    InvalidCredentialsError,
    NoInviteError,
    PermissionDeniedError,
)
from app.invites.models import InviteStatus
from app.invites.service import InviteService
from app.users.models import OAuthAccountDB, UserDB, WorkspaceRole
from app.users.service import UserService
from app.workspaces.models import WorkspaceMembershipDB
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.schemas import WorkspaceCreate


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.invites = InviteService(db)
        self.authentication = WorkspaceAuthenticationService(db)
        self.workspaces = WorkspaceRepository(db)

    async def count_users(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(UserDB))
        return result.scalar_one()

    @staticmethod
    def _parse_workspace_id(value: str | None) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(value)
        except ValueError as exc:
            raise DomainValidationError("Invalid active workspace") from exc

    async def resolve_workspace_id(self, value: str | None) -> UUID | None:
        workspace_id = self._parse_workspace_id(value)
        if workspace_id is not None and await self.workspaces.get(workspace_id) is None:
            raise DomainValidationError("Invalid active workspace")
        return workspace_id

    async def _ensure_password_auth(self, workspace_id: UUID | None) -> None:
        if workspace_id is not None and not await self.authentication.password_enabled(
            workspace_id
        ):
            raise PermissionDeniedError("Password authentication is disabled")

    def build_jwt_for_user(self, user: UserDB) -> tuple[UserDB, str]:
        return user, create_access_token(user.id)

    async def hydrate_default_workspace(self, user: UserDB) -> UUID | None:
        membership = await self.workspaces.get_first_membership(user.id)
        if membership is None:
            return None
        user.set_workspace_membership(membership)
        return membership.workspace_id

    async def hydrate_signin_workspace(
        self, user: UserDB, workspace_value: str | None
    ) -> UUID | None:
        """Hydrate the workspace selected by the browser, with a safe fallback.

        The active-workspace cookie is a navigation hint, not a credential. It
        can outlive a deleted workspace or revoked membership, so an unusable
        value must not prevent an otherwise valid sign-in.
        """
        if workspace_value is not None:
            try:
                workspace_id = UUID(workspace_value)
            except ValueError:
                pass
            else:
                membership = await self.workspaces.get_membership(workspace_id, user.id)
                if membership is not None:
                    user.set_workspace_membership(membership)
                    return workspace_id
        return await self.hydrate_default_workspace(user)

    async def hydrate_workspace(self, user: UserDB, workspace_id: UUID) -> None:
        membership = await self.workspaces.get_membership(workspace_id, user.id)
        if membership is None:
            raise InvalidCredentialsError("Invalid email or password")
        user.set_workspace_membership(membership)

    async def _add_invited_membership(
        self, user: UserDB, invite_workspace_id: UUID, role: str, team_id: UUID | None
    ) -> WorkspaceMembershipDB:
        membership = await self.workspaces.get_membership(invite_workspace_id, user.id)
        if membership is None:
            membership = await self.workspaces.create_membership(
                WorkspaceMembershipDB(
                    workspace_id=invite_workspace_id,
                    user_id=user.id,
                    role=WorkspaceRole(role),
                    team_id=team_id,
                )
            )
        user.set_workspace_membership(membership)
        return membership

    async def _ensure_email_available(self, email: str) -> None:
        result = await self.db.execute(select(UserDB).where(UserDB.email == email))
        if result.scalar_one_or_none() is not None:
            raise AlreadyExistsError("Email already registered")

    async def signin(
        self, data: SigninRequest, workspace_value: str | None
    ) -> tuple[UserDB, str]:
        result = await self.db.execute(select(UserDB).where(UserDB.email == data.email))
        user = result.scalar_one_or_none()
        if user is None or user.password_hash is None:
            raise InvalidCredentialsError("Invalid email or password")
        if not await verify_password(data.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")
        workspace_id = await self.hydrate_signin_workspace(user, workspace_value)
        await self._ensure_password_auth(workspace_id)
        if user.two_factor_enabled:
            return user, create_scoped_token(user.id, "two_factor_signin")
        return self.build_jwt_for_user(user)

    async def verify_two_factor_signin(
        self,
        challenge_token: str,
        data: TwoFactorSigninVerifyRequest,
        workspace_value: str | None,
    ) -> tuple[UserDB, str]:
        decoded = decode_scoped_token(challenge_token, "two_factor_signin")
        if decoded is None:
            raise InvalidCredentialsError("Two-factor challenge has expired")
        await record_challenge_attempt(decoded.user_id, decoded.jti)
        user = await self.db.get(UserDB, decoded.user_id)
        if user is None or not user.two_factor_enabled:
            raise InvalidCredentialsError("Invalid two-factor challenge")
        await UserService(self.db).verify_second_factor(user.id, data.code)
        await consume_challenge(decoded.jti)
        await self.hydrate_signin_workspace(user, workspace_value)
        return self.build_jwt_for_user(user)

    async def setup(self, data: SignupRequest) -> tuple[UserDB, str]:
        if await self.count_users() > 0:
            raise PermissionDeniedError("Setup already completed")
        user = UserDB(
            email=data.email,
            name=data.name,
            password_hash=await get_password_hash(data.password),
            can_create_workspace=True,
            is_instance_owner=True,
        )
        self.db.add(user)
        await self.db.flush()
        workspace = await self.workspaces.get_first_workspace()
        if workspace is None:
            workspace = await self.workspaces.create(
                WorkspaceCreate(name="Default workspace")
            )
        membership = await self.workspaces.create_membership(
            WorkspaceMembershipDB(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.admin,
            )
        )
        await self.db.refresh(user)
        user.set_workspace_membership(membership)
        return self.build_jwt_for_user(user)

    async def accept_invite(self, data: InviteAcceptRequest) -> tuple[UserDB, str]:
        invite = await self.invites.get_by_token(data.token)
        if not invite:
            raise DomainValidationError("Invalid or expired invite")
        await self._ensure_password_auth(invite.workspace_id)
        first_name = data.first_name.strip()
        last_name = data.last_name.strip()
        if not first_name or not last_name:
            raise DomainValidationError("First and last name are required")
        result = await self.db.execute(
            select(UserDB).where(UserDB.email == invite.email)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = UserDB(
                email=invite.email,
                name=f"{first_name} {last_name}",
                first_name=first_name,
                last_name=last_name,
                password_hash=await get_password_hash(data.password),
            )
            self.db.add(user)
            await self.db.flush()
        elif user.password_hash is None or not await verify_password(
            data.password, user.password_hash
        ):
            raise InvalidCredentialsError("Invalid email or password")
        membership = await self._add_invited_membership(
            user,
            invite.workspace_id,
            invite.role,
            invite.team_id,
        )
        invite.status = InviteStatus.accepted
        self.db.add(invite)
        await self.db.flush()
        await self.db.refresh(user)
        user.set_workspace_membership(membership)
        if user.two_factor_enabled:
            return user, create_scoped_token(user.id, "two_factor_signin")
        return self.build_jwt_for_user(user)

    def _refresh_picture(self, user: UserDB, picture_url: str | None) -> None:
        """Update the cached avatar from the provider's claim on each sign-in.

        Provider photo URLs rotate when users change their picture, so the
        stored value is a cache refreshed at every OAuth sign-in. ``None`` is
        left alone: a provider that stops sending the claim (or a secondary
        provider without one) must not erase a previously stored avatar.
        """
        if picture_url and user.picture_url != picture_url:
            user.picture_url = picture_url
            self.db.add(user)

    async def oauth_signin_or_link(
        self,
        provider: str,
        sub_id: str,
        email: str,
        name: str | None,
        picture_url: str | None,
        invite_token: str | None,
        workspace_id: UUID,
    ) -> tuple[UserDB, str]:
        """Resolve an OAuth/OIDC identity to a user.

        - Existing OAuth link → returns the linked user.
        - Matching user by email → creates an OAuth link.
        - New user → requires a valid invite (by token or by email).

        Raises :class:`NoInviteError` when a new user has no invite — the
        router converts this to a redirect with an error param.
        """
        result = await self.db.execute(
            select(OAuthAccountDB).where(
                OAuthAccountDB.provider == provider,
                OAuthAccountDB.sub_id == sub_id,
            )
        )
        oauth_account = result.scalar_one_or_none()

        if oauth_account:
            result = await self.db.execute(
                select(UserDB).where(UserDB.id == oauth_account.user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                raise DomainError("Linked user not found")
            self._refresh_picture(user, picture_url)
            if invite_token:
                invite = await self.invites.get_by_token(invite_token)
                if (
                    not invite
                    or invite.email != email
                    or invite.workspace_id != workspace_id
                ):
                    raise NoInviteError("No invite found for this email")
                await self._add_invited_membership(
                    user,
                    invite.workspace_id,
                    invite.role,
                    invite.team_id,
                )
                invite.status = InviteStatus.accepted
                self.db.add(invite)
            else:
                await self.hydrate_workspace(user, workspace_id)
            await self.db.flush()
            return self.build_jwt_for_user(user)

        result = await self.db.execute(select(UserDB).where(UserDB.email == email))
        user = result.scalar_one_or_none()

        if user:
            self.db.add(
                OAuthAccountDB(
                    provider=provider,
                    sub_id=sub_id,
                    user_id=user.id,
                )
            )
            self._refresh_picture(user, picture_url)
            if invite_token:
                invite = await self.invites.get_by_token(invite_token)
                if (
                    not invite
                    or invite.email != email
                    or invite.workspace_id != workspace_id
                ):
                    raise NoInviteError("No invite found for this email")
                await self._add_invited_membership(
                    user,
                    invite.workspace_id,
                    invite.role,
                    invite.team_id,
                )
                invite.status = InviteStatus.accepted
                self.db.add(invite)
            else:
                await self.hydrate_workspace(user, workspace_id)
            await self.db.flush()
            return self.build_jwt_for_user(user)

        invite = None
        if invite_token:
            invite = await self.invites.get_by_token(invite_token)
        if not invite:
            invite = await self.invites.get_pending_by_email(email, workspace_id)
        if not invite or invite.workspace_id != workspace_id:
            raise NoInviteError("No invite found for this email")

        user = UserDB(
            email=email,
            name=name,
            picture_url=picture_url,
        )
        self.db.add(user)
        await self.db.flush()
        await self._add_invited_membership(
            user,
            invite.workspace_id,
            invite.role,
            invite.team_id,
        )

        self.db.add(
            OAuthAccountDB(
                provider=provider,
                sub_id=sub_id,
                user_id=user.id,
            )
        )
        invite.status = InviteStatus.accepted
        self.db.add(invite)
        await self.db.flush()
        await self.db.refresh(user)
        return self.build_jwt_for_user(user)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)
