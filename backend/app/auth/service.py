"""Authentication business logic.

Keeps ``auth/router.py`` thin by centralizing signup/signin/OAuth flows here.
Services return the freshly authenticated ``UserDB`` plus a JWT string; the
router is responsible for attaching the auth cookie to the response.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.auth.schemas import InviteAcceptRequest, SigninRequest, SignupRequest
from app.auth.settings import auth_settings
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


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.invites = InviteService(db)

    async def count_users(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(UserDB))
        return result.scalar_one()

    def _ensure_password_auth(self) -> None:
        if not auth_settings.password_enabled:
            raise PermissionDeniedError("Password authentication is disabled")

    def build_jwt_for_user(self, user: UserDB) -> tuple[UserDB, str]:
        return user, create_access_token(user.id)

    async def _ensure_email_available(self, email: str) -> None:
        result = await self.db.execute(select(UserDB).where(UserDB.email == email))
        if result.scalar_one_or_none() is not None:
            raise AlreadyExistsError("Email already registered")

    async def signin(self, data: SigninRequest) -> tuple[UserDB, str]:
        self._ensure_password_auth()
        result = await self.db.execute(select(UserDB).where(UserDB.email == data.email))
        user = result.scalar_one_or_none()
        if user is None or user.password_hash is None:
            raise InvalidCredentialsError("Invalid email or password")
        if not await verify_password(data.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")
        return self.build_jwt_for_user(user)

    async def setup(self, data: SignupRequest) -> tuple[UserDB, str]:
        if await self.count_users() > 0:
            raise PermissionDeniedError("Setup already completed")
        user = UserDB(
            email=data.email,
            name=data.name,
            password_hash=await get_password_hash(data.password),
            role=WorkspaceRole.admin,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return self.build_jwt_for_user(user)

    async def accept_invite(self, data: InviteAcceptRequest) -> tuple[UserDB, str]:
        self._ensure_password_auth()
        invite = await self.invites.get_by_token(data.token)
        if not invite:
            raise DomainValidationError("Invalid or expired invite")
        await self._ensure_email_available(invite.email)

        user = UserDB(
            email=invite.email,
            name=data.name,
            password_hash=await get_password_hash(data.password),
            role=WorkspaceRole(invite.role),
            team_id=invite.team_id,
        )
        self.db.add(user)
        invite.status = InviteStatus.accepted
        self.db.add(invite)
        await self.db.flush()
        await self.db.refresh(user)
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
            await self.db.flush()
            return self.build_jwt_for_user(user)

        invite = None
        if invite_token:
            invite = await self.invites.get_by_token(invite_token)
        if not invite:
            invite = await self.invites.get_pending_by_email(email)
        if not invite:
            raise NoInviteError("No invite found for this email")

        user = UserDB(
            email=email,
            name=name,
            picture_url=picture_url,
            role=WorkspaceRole(invite.role),
            team_id=invite.team_id,
        )
        self.db.add(user)
        await self.db.flush()

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
