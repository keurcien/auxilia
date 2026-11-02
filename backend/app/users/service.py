from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.appearance.service import InstanceAppearanceService
from app.auth.configuration import WorkspaceAuthenticationService
from app.auth.two_factor import (
    build_otpauth_uri,
    build_qr_code_data_url,
    create_scoped_token,
    decode_scoped_token,
    find_backup_code,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    matching_totp_counter,
)
from app.auth.utils import get_password_hash, verify_password
from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    InvalidCredentialsError,
    NotFoundError,
)
from app.memories.service import MemoryService
from app.pagination import Page, PageParams
from app.service import BaseService
from app.teams.repository import TeamRepository
from app.users.models import UserDB, UserImageDB, UserTwoFactorDB, WorkspaceRole
from app.users.repository import UserRepository
from app.users.schemas import (
    BackupCodesResponse,
    InstanceUserMembershipResponse,
    InstanceUserResponse,
    PasswordChange,
    ProfilePatch,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorRegenerateRequest,
    TwoFactorSetupRequest,
    TwoFactorSetupResponse,
    TwoFactorStatus,
    UserCreate,
    UserCreateDB,
    UserPatch,
    UserPromptActivityResponse,
    UserResponse,
    UserRoleCounts,
    UserRolePatch,
    UserTeamPatch,
)
from app.utils.encryption import decrypt_value, encrypt_value
from app.utils.images import ProcessedImage
from app.workspaces.models import WorkspaceMembershipDB
from app.workspaces.repository import WorkspaceRepository


class UserService(BaseService[UserDB, UserRepository]):
    not_found_message = "User not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, UserRepository(db))
        self.memory_service = MemoryService(db)
        self.team_repository = TeamRepository(db)
        self.workspace_repository = WorkspaceRepository(db)

    async def _ensure_email_available(self, email: str) -> None:
        if await self.repository.get_by_email(email):
            raise AlreadyExistsError("Email already registered")

    async def create(self, data: UserCreate, workspace_id: UUID) -> UserDB:
        if data.email:
            await self._ensure_email_available(data.email)
        user_data = UserCreateDB.model_validate(data.model_dump(exclude={"role"}))
        user = await self.repository.create(user_data)
        await self.memory_service.enable_auto_capture_for_new_user(user.id)
        membership = await self.workspace_repository.create_membership(
            WorkspaceMembershipDB(
                workspace_id=workspace_id,
                user_id=user.id,
                role=data.role,
            )
        )
        user.set_workspace_membership(membership)
        return user

    async def _get_in_workspace(
        self, user_id: UUID, workspace_id: UUID
    ) -> tuple[UserDB, WorkspaceMembershipDB]:
        row = await self.repository.get_in_workspace(user_id, workspace_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        return row

    async def get(self, user_id: UUID, workspace_id: UUID) -> UserDB:
        user, membership = await self._get_in_workspace(user_id, workspace_id)
        user.set_workspace_membership(membership)
        return user

    async def get_by_email(self, email: str, workspace_id: UUID) -> UserDB:
        user = await self.repository.get_by_email(email)
        if not user:
            raise NotFoundError(self.not_found_message)
        return await self.get(user.id, workspace_id)

    async def update_profile(self, user: UserDB, data: ProfilePatch) -> UserDB:
        if "first_name" in data.model_fields_set:
            user.first_name = (data.first_name or "").strip() or None
        if "last_name" in data.model_fields_set:
            user.last_name = (data.last_name or "").strip() or None
        user.name = (
            " ".join(part for part in (user.first_name, user.last_name) if part).strip()
            or None
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def change_password(self, user: UserDB, data: PasswordChange) -> None:
        await self._verify_current_password(user, data.current_password)
        user.password_hash = await get_password_hash(data.new_password)
        self.db.add(user)
        await self.db.flush()

    async def get_image(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        instance_owner: bool = False,
    ) -> UserImageDB:
        if instance_owner:
            await self.get_or_404(user_id)
        else:
            await self._get_in_workspace(user_id, workspace_id)
        image = await self.repository.get_image(user_id)
        if image is None:
            raise NotFoundError("User image not found")
        return image

    async def set_image(self, user_id: UUID, image: ProcessedImage) -> UUID:
        await self.get_or_404(user_id)
        revision = uuid4()
        await self.repository.set_image(
            user_id,
            data=image.data,
            media_type=image.media_type,
            sha256=image.sha256,
            revision=revision,
        )
        return revision

    async def delete_image(self, user_id: UUID) -> None:
        await self.get_or_404(user_id)
        await self.repository.delete_image(user_id)

    async def get_two_factor_status(self, user: UserDB) -> TwoFactorStatus:
        two_factor = await self.repository.get_two_factor(user.id)
        return TwoFactorStatus(
            enabled=user.two_factor_enabled and two_factor is not None,
            backup_codes_remaining=(
                len(two_factor.backup_code_hashes) if two_factor else 0
            ),
        )

    async def begin_two_factor_setup(
        self, user: UserDB, data: TwoFactorSetupRequest
    ) -> TwoFactorSetupResponse:
        if user.two_factor_enabled:
            raise DomainValidationError("Two-factor authentication is already enabled")
        await self._verify_current_password(user, data.current_password)
        secret = generate_totp_secret()
        app_name = (await InstanceAppearanceService(self.db).get_settings()).app_name
        otpauth_uri = build_otpauth_uri(
            secret, user.email or str(user.id), issuer=app_name
        )
        return TwoFactorSetupResponse(
            secret=secret,
            otpauth_uri=otpauth_uri,
            qr_code_data_url=build_qr_code_data_url(otpauth_uri),
            setup_token=create_scoped_token(user.id, "two_factor_setup", secret=secret),
        )

    async def confirm_two_factor_setup(
        self, user: UserDB, data: TwoFactorConfirmRequest
    ) -> BackupCodesResponse:
        decoded = decode_scoped_token(data.setup_token, "two_factor_setup")
        if decoded is None or decoded.user_id != user.id or not decoded.secret:
            raise DomainValidationError("Two-factor setup has expired")
        locked_user = await self.repository.get_for_update(user.id)
        if locked_user is None:
            raise NotFoundError(self.not_found_message)
        if locked_user.two_factor_enabled:
            raise DomainValidationError("Two-factor authentication is already enabled")
        secret = decoded.secret
        counter = matching_totp_counter(secret, data.code)
        if counter is None:
            raise InvalidCredentialsError("Invalid authentication code")
        backup_codes = generate_backup_codes()
        await self.repository.set_two_factor(
            user.id,
            secret_encrypted=encrypt_value(secret),
            backup_code_hashes=[hash_backup_code(code) for code in backup_codes],
            last_used_totp_counter=counter,
        )
        return BackupCodesResponse(backup_codes=backup_codes)

    async def disable_two_factor(
        self, user: UserDB, data: TwoFactorDisableRequest
    ) -> None:
        if (
            user.active_workspace_id is not None
            and await WorkspaceAuthenticationService(self.db).enforces_two_factor(
                user.active_workspace_id
            )
        ):
            raise DomainValidationError(
                "Two-factor authentication is required by your workspace"
            )
        await self._verify_current_password(user, data.current_password)
        await self.verify_second_factor(user.id, data.code)
        await self.repository.disable_two_factor(user.id)

    async def regenerate_backup_codes(
        self, user: UserDB, data: TwoFactorRegenerateRequest
    ) -> BackupCodesResponse:
        await self._verify_current_password(user, data.current_password)
        two_factor = await self.verify_second_factor(user.id, data.code)
        backup_codes = generate_backup_codes()
        await self.repository.set_backup_code_hashes(
            two_factor,
            [hash_backup_code(code) for code in backup_codes],
        )
        return BackupCodesResponse(backup_codes=backup_codes)

    async def verify_second_factor(self, user_id: UUID, code: str) -> UserTwoFactorDB:
        two_factor = await self.repository.get_two_factor(user_id, for_update=True)
        if two_factor is None:
            raise InvalidCredentialsError("Two-factor authentication is not enabled")
        secret = decrypt_value(two_factor.secret_encrypted)
        counter = matching_totp_counter(secret, code)
        if counter is not None and (
            two_factor.last_used_totp_counter is None
            or counter > two_factor.last_used_totp_counter
        ):
            two_factor.last_used_totp_counter = counter
            self.db.add(two_factor)
            await self.db.flush()
            return two_factor
        backup_index = find_backup_code(code, two_factor.backup_code_hashes)
        if backup_index is None:
            raise InvalidCredentialsError("Invalid authentication code")
        remaining = list(two_factor.backup_code_hashes)
        remaining.pop(backup_index)
        await self.repository.set_backup_code_hashes(two_factor, remaining)
        return two_factor

    @staticmethod
    async def _verify_current_password(
        user: UserDB, current_password: str | None
    ) -> None:
        if user.password_hash is None:
            return
        if not current_password or not await verify_password(
            current_password, user.password_hash
        ):
            raise InvalidCredentialsError("Current password is incorrect")

    async def list(
        self,
        workspace_id: UUID,
        page: PageParams,
        role: WorkspaceRole | None = None,
        search: str | None = None,
        team_id: UUID | None = None,
    ) -> Page[UserResponse]:
        rows, total = await self.repository.list(
            workspace_id, page, role=role, search=search, team_id=team_id
        )
        items = []
        for user, membership in rows:
            user.set_workspace_membership(membership)
            items.append(UserResponse.model_validate(user))
        return Page.build(items, total, page)

    async def list_prompt_activity(
        self,
        user_ids: list[UUID],
        *,
        workspace_id: UUID | None,
    ) -> list[UserPromptActivityResponse]:
        unique_ids = list(dict.fromkeys(user_ids))
        if len(unique_ids) > 100:
            raise DomainValidationError("At most 100 users can be requested")
        activity = await self.repository.get_prompt_activity(
            unique_ids,
            workspace_id=workspace_id,
        )
        return [
            UserPromptActivityResponse(
                user_id=user_id,
                last_prompt_at=activity.get(user_id, (None, False))[0],
                has_active_prompt=activity.get(user_id, (None, False))[1],
            )
            for user_id in unique_ids
        ]

    async def list_instance_users(
        self,
        page: PageParams,
        *,
        role: WorkspaceRole | None = None,
        search: str | None = None,
        team_id: UUID | None = None,
    ) -> Page[InstanceUserResponse]:
        users, total = await self.repository.list_instance_users(
            page,
            role=role,
            search=search,
            team_id=team_id,
        )
        rows = await self.repository.list_workspace_memberships_for_users(
            [user.id for user in users]
        )
        memberships: dict[UUID, list[InstanceUserMembershipResponse]] = {
            user.id: [] for user in users
        }
        for membership, workspace in rows:
            memberships[membership.user_id].append(
                InstanceUserMembershipResponse(
                    workspace_id=workspace.id,
                    workspace_name=workspace.name,
                    role=membership.role,
                    team_id=membership.team_id,
                )
            )
        items = [
            InstanceUserResponse.model_validate(
                user,
                update={"memberships": memberships[user.id]},
            )
            for user in users
        ]
        return Page.build(items, total, page)

    async def count_by_role(self, workspace_id: UUID) -> UserRoleCounts:
        counts = await self.repository.count_by_role(workspace_id)
        return UserRoleCounts(
            total=sum(counts.values()),
            member=counts.get(WorkspaceRole.member, 0),
            editor=counts.get(WorkspaceRole.editor, 0),
            admin=counts.get(WorkspaceRole.admin, 0),
        )

    async def list_by_ids(self, user_ids: list[UUID]) -> list[UserDB]:
        return await self.repository.list_by_ids(user_ids)

    async def update(
        self, user_id: UUID, workspace_id: UUID, data: UserPatch
    ) -> UserDB:
        user, membership = await self._get_in_workspace(user_id, workspace_id)
        update_data = data.model_dump(exclude_unset=True)
        new_email = update_data.get("email")
        if "email" in update_data and new_email is not None and new_email != user.email:
            await self._ensure_email_available(new_email)
        if user.is_instance_owner and update_data.get("can_create_workspace") is False:
            raise DomainValidationError(
                "The instance owner must be allowed to create workspaces"
            )
        updated = await self.repository.update(user, data)
        updated.set_workspace_membership(membership)
        return updated

    async def update_role(
        self, user_id: UUID, workspace_id: UUID, data: UserRolePatch
    ) -> UserDB:
        user, membership = await self._get_in_workspace(user_id, workspace_id)
        if data.role != membership.role:
            await self._ensure_agent_access_survives_identity_change(
                user_id,
                workspace_id,
                role=data.role,
                team_id=membership.team_id,
            )
        membership.role = data.role
        self.db.add(membership)
        await self.db.flush()
        user.set_workspace_membership(membership)
        return user

    async def update_team(
        self, user_id: UUID, workspace_id: UUID, data: UserTeamPatch
    ) -> UserDB:
        user, membership = await self._get_in_workspace(user_id, workspace_id)
        if (
            data.team_id is not None
            and not await self.team_repository.get_in_workspace_for_key_share(
                data.team_id, workspace_id
            )
        ):
            raise NotFoundError("Team not found")
        if data.team_id != membership.team_id:
            await self._ensure_agent_access_survives_identity_change(
                user_id,
                workspace_id,
                role=membership.role,
                team_id=data.team_id,
            )
        membership.team_id = data.team_id
        self.db.add(membership)
        await self.db.flush()
        user.set_workspace_membership(membership)
        return user

    async def delete(self, user_id: UUID, workspace_id: UUID) -> None:
        _, membership = await self._get_in_workspace(user_id, workspace_id)
        from app.agents.core.repository import AgentRepository

        await AgentRepository(self.db, workspace_id).delete_permissions_for_user(
            user_id
        )
        await self.workspace_repository.delete_membership(membership)

    async def _ensure_agent_access_survives_identity_change(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        role: WorkspaceRole,
        team_id: UUID | None,
    ) -> None:
        from app.agents.core.repository import AgentRepository
        from app.agents.core.service import AgentService
        from app.agents.models import EffectivePermission
        from app.exceptions import PermissionDeniedError
        from app.triggers.repository import TriggerRepository

        repository = AgentRepository(self.db, workspace_id)
        service = AgentService(self.db, workspace_id)
        granted_agent_ids = set(await repository.list_granted_agent_ids(user_id))
        trigger_agent_ids = await TriggerRepository(
            self.db, workspace_id
        ).list_active_agent_ids_requiring_user_access(user_id)
        for agent_id in granted_agent_ids | trigger_agent_ids:
            try:
                await service.require_permission(
                    agent_id,
                    at_least=EffectivePermission.member,
                    action="use this agent",
                    user_id=user_id,
                    user_role=role,
                    user_team_id=team_id,
                    include_archived=True,
                )
            except (NotFoundError, PermissionDeniedError) as exc:
                raise DomainValidationError(
                    "This role or team change would disable an active trigger"
                ) from exc
            await service.ensure_dependencies_visible_to_identity(
                agent_id,
                user_id=user_id,
                user_role=role,
                user_team_id=team_id,
            )


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)
