from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.core.service import AgentService
from app.agents.models import EffectivePermission, ToolStatus
from app.auth.settings import auth_settings
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.model_providers.service import ModelService
from app.projects.models import ProjectDB
from app.projects.repository import ProjectRepository
from app.projects.service import ProjectService
from app.realtime.schemas import WorkspaceEventKind
from app.realtime.service import stage_workspace_event
from app.runtime.runs.service import RunService
from app.service import BaseService
from app.teams.repository import TeamRepository
from app.threads.models import ThreadSource
from app.threads.schemas import ThreadCreate
from app.threads.service import ThreadService
from app.triggers.models import TriggerDB, TriggerType
from app.triggers.repository import TriggerRepository
from app.triggers.schedule import compute_next_run_at, ensure_valid_schedule
from app.triggers.schemas import (
    TriggerCreate,
    TriggerCreateDB,
    TriggerPatch,
    TriggerResponse,
    TriggerRunResponse,
    TriggerThreadResponse,
    WebhookTriggerInvoke,
)
from app.triggers.settings import trigger_settings
from app.users.models import UserDB, WorkspaceRole
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)

_RESOURCE_FIELDS = (
    "disabled_mcp_server_ids",
    "disabled_skill_ids",
    "disabled_sandbox_ids",
    "disabled_subagent_ids",
)
_TOOL_RESOURCE_FIELD = "disabled_mcp_tools"


class TriggerService(BaseService[TriggerDB, TriggerRepository]):
    not_found_message = "Trigger not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, TriggerRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.agent_service = AgentService(db, workspace_id)
        self.model_service = ModelService(db, workspace_id)
        self.teams = TeamRepository(db)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_can_manage(trigger: TriggerDB, user: UserDB) -> None:
        if trigger.owner_id != user.id and user.role != WorkspaceRole.admin:
            raise PermissionDeniedError("Not authorized to access this trigger")

    async def _ensure_agent_usable(
        self, agent_id: UUID, owner: UserDB, workspace_id: UUID | None = None
    ) -> None:
        """The trigger's agent must be one its *owner* is allowed to use —
        runs execute with the owner's identity and MCP credentials."""
        try:
            await AgentService(
                self.db, workspace_id or self.workspace_id
            ).require_permission(
                agent_id,
                at_least=EffectivePermission.member,
                action="use this agent",
                user_id=owner.id,
                user_role=owner.role,
                user_team_id=owner.team_id,
            )
        except PermissionDeniedError as exc:
            # The gate speaks for the *caller*; here the caller may be an admin
            # creating a trigger for someone else, so name whose access failed.
            raise PermissionDeniedError(
                "Trigger owner is not allowed to use this agent"
            ) from exc

    async def _ensure_agent_scope(
        self,
        agent_id: UUID,
        *,
        visibility,
        owner_id: UUID,
        team_ids: list[UUID],
        trigger_owner_id: UUID,
    ) -> None:
        agents = AgentRepository(self.db, self.workspace_id)
        agent = await agents.get_scoped_for_update(agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        if visibility == ResourceVisibility.personal:
            if owner_id != trigger_owner_id:
                membership = await WorkspaceRepository(self.db).get_membership(
                    agent.workspace_id, owner_id
                )
                if membership is None:
                    raise DomainValidationError(
                        "Project owner no longer belongs to the workspace"
                    )
                try:
                    await AgentService(self.db, agent.workspace_id).require_permission(
                        agent_id,
                        at_least=EffectivePermission.member,
                        action="use this agent",
                        user_id=owner_id,
                        user_role=membership.role,
                        user_team_id=membership.team_id,
                    )
                except (NotFoundError, PermissionDeniedError) as exc:
                    raise DomainValidationError(
                        "Project owner is not allowed to use this trigger's agent"
                    ) from exc
            return
        if not audience_contains(
            parent_visibility=visibility,
            parent_owner_id=owner_id,
            parent_team_ids=set(team_ids),
            child_visibility=agent.visibility,
            child_owner_id=agent.owner_id,
            child_team_ids=(
                set(await agents.get_team_ids(agent.id))
                if agent.visibility == ResourceVisibility.teams
                else set()
            ),
        ):
            raise DomainValidationError(
                f"Agent '{agent.name}' is more private than this trigger"
            )

    async def _get_owner(self, trigger: TriggerDB) -> UserDB:
        owner = await self.db.get(UserDB, trigger.owner_id)
        if owner is None:  # FK guarantees this in practice
            raise DomainValidationError("Trigger owner no longer exists")
        membership = await WorkspaceRepository(self.db).get_membership(
            trigger.workspace_id, owner.id
        )
        if membership is None:
            raise DomainValidationError("Trigger owner no longer belongs to workspace")
        owner.set_workspace_membership(membership)
        return owner

    async def _ensure_project_visible_to_owner(
        self, trigger: TriggerDB, owner: UserDB
    ) -> None:
        if trigger.project_id is None:
            return
        projects = ProjectRepository(self.db, trigger.workspace_id)
        project = await projects.get(trigger.project_id)
        if project is None:
            raise DomainValidationError("Trigger project no longer exists")
        team_ids = (
            set(await projects.list_team_ids(project.id))
            if project.visibility == ResourceVisibility.teams
            else set()
        )
        if not is_resource_visible(
            visibility=project.visibility,
            owner_id=project.owner_id,
            team_ids=team_ids,
            user=owner,
        ):
            raise PermissionDeniedError(
                "Trigger owner can no longer access this project"
            )

    async def _normalize_resource_selection(
        self,
        agent_id: UUID,
        selection: dict[str, list[UUID] | dict[UUID, list[str]] | None],
        *,
        project_id: UUID | None = None,
    ) -> dict[str, list[str] | dict[str, list[str]] | None]:
        """Validate explicit trigger overrides against the selected agent graph."""
        if not selection:
            return {}
        spec = await AgentRepository(self.db, self.workspace_id).get_run_spec(agent_id)
        if spec is None:
            raise NotFoundError("Agent not found")
        selected_ids = {
            field: value if isinstance(value, list) else []
            for field in _RESOURCE_FIELDS
            if (value := selection.get(field)) is not None
        }
        normalized = await ThreadService(
            self.db, self.workspace_id
        ).normalize_resource_ids(
            spec,
            selected_ids.get("disabled_mcp_server_ids", []),
            selected_ids.get("disabled_skill_ids", []),
            selected_ids.get("disabled_sandbox_ids", []),
            selected_ids.get("disabled_subagent_ids", []),
            project_id=project_id,
        )
        result: dict[str, list[str] | dict[str, list[str]] | None] = {
            field: normalized[index] if selection.get(field) is not None else None
            for index, field in enumerate(_RESOURCE_FIELDS)
            if field in selection
        }
        if _TOOL_RESOURCE_FIELD in selection:
            tool_selection = selection[_TOOL_RESOURCE_FIELD]
            if tool_selection is None:
                result[_TOOL_RESOURCE_FIELD] = None
            elif isinstance(tool_selection, dict):
                available: dict[UUID, set[str]] = {}
                safe_defaults: dict[UUID, list[str]] = {}
                for binding in spec.all_mcp_bindings:
                    names = available.setdefault(binding.mcp_server_id, set())
                    names.update(
                        name
                        for name, status in (binding.tools or {}).items()
                        if status != ToolStatus.disabled
                    )
                    rejected = safe_defaults.setdefault(binding.mcp_server_id, [])
                    rejected.extend(
                        name
                        for name, status in (binding.tools or {}).items()
                        if status == ToolStatus.needs_approval and name not in rejected
                    )
                normalized_tools = {
                    str(server_id): tool_names
                    for server_id, tool_names in safe_defaults.items()
                }
                for server_id, tool_names in tool_selection.items():
                    unknown = set(tool_names) - available.get(server_id, set())
                    if server_id not in available or unknown:
                        raise DomainValidationError(
                            "Tool selection contains tools unavailable to this agent"
                        )
                    normalized_tools[str(server_id)] = list(dict.fromkeys(tool_names))
                result[_TOOL_RESOURCE_FIELD] = normalized_tools
        return result

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------

    async def _to_responses(
        self, triggers: list[TriggerDB], user: UserDB
    ) -> list[TriggerResponse]:
        """Project to responses with `model_available` and the whitelist
        display name stamped — one availability lookup for the whole batch,
        not one per trigger."""
        available = {m.model_id for m in await self.model_service.list_available()}
        names = {
            m.model_id: m.display_name for m in await self.model_service.list_catalog()
        }
        direct_team_ids = await self.repository.list_team_ids_for_triggers(
            [
                trigger.id
                for trigger in triggers
                if trigger.visibility == ResourceVisibility.teams
            ]
        )
        projects = ProjectRepository(self.db, self.workspace_id)
        responses: list[TriggerResponse] = []
        for trigger in triggers:
            (
                _project,
                effective_visibility,
                _,
                effective_team_ids,
            ) = await self._effective_audience(trigger, projects)
            responses.append(
                TriggerResponse.model_validate(
                    trigger,
                    update={
                        "team_ids": direct_team_ids.get(trigger.id, []),
                        "effective_visibility": effective_visibility,
                        "effective_team_ids": list(effective_team_ids),
                        "can_manage": (
                            user.id == trigger.owner_id
                            or user.role == WorkspaceRole.admin
                        ),
                        "model_available": trigger.model_id in available,
                        "model_display_name": names.get(trigger.model_id),
                        "webhook_url": (
                            f"{auth_settings.FRONTEND_URL.rstrip('/')}"
                            f"/api/backend/triggers/webhooks/{trigger.webhook_id}"
                            if trigger.webhook_id is not None
                            and (
                                user.id == trigger.owner_id
                                or user.role == WorkspaceRole.admin
                            )
                            else None
                        ),
                    },
                )
            )
        return responses

    async def _effective_audience(
        self,
        trigger: TriggerDB,
        projects: ProjectRepository | None = None,
    ) -> tuple[ProjectDB | None, ResourceVisibility, UUID, set[UUID]]:
        if trigger.project_id is not None:
            projects = projects or ProjectRepository(self.db, trigger.workspace_id)
            project = await projects.get(trigger.project_id)
            if project is not None:
                team_ids = (
                    set(await projects.list_team_ids(project.id))
                    if project.visibility == ResourceVisibility.teams
                    else set()
                )
                return (
                    project,
                    project.visibility,
                    project.owner_id,
                    team_ids,
                )
        team_ids = (
            set(await self.repository.list_team_ids(trigger.id))
            if trigger.visibility == ResourceVisibility.teams
            else set()
        )
        return None, trigger.visibility, trigger.owner_id, team_ids

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list(self, user: UserDB) -> list[TriggerResponse]:
        triggers = await self.repository.list_all()
        visible: list[TriggerDB] = []
        projects = ProjectRepository(self.db, self.workspace_id)
        for trigger in triggers:
            _, visibility, owner_id, team_ids = await self._effective_audience(
                trigger, projects
            )
            if trigger.owner_id == user.id or is_resource_visible(
                visibility=visibility,
                owner_id=owner_id,
                team_ids=team_ids,
                user=user,
            ):
                visible.append(trigger)
        return await self._to_responses(visible, user)

    async def get(self, trigger_id: UUID, user: UserDB) -> TriggerResponse:
        trigger = await self.get_or_404(trigger_id)
        await self._ensure_visible(trigger, user)
        return (await self._to_responses([trigger], user))[0]

    async def list_threads(
        self, trigger_id: UUID, user: UserDB
    ) -> list[TriggerThreadResponse]:
        """Past firings (one thread per firing), last 30 days, newest first."""
        trigger = await self.get_or_404(trigger_id)
        await self._ensure_visible(trigger, user)
        since = datetime.now(UTC) - timedelta(days=30)
        threads = await ThreadService(self.db, trigger.workspace_id).list_for_trigger(
            trigger_id, since=since
        )
        return [TriggerThreadResponse.model_validate(t) for t in threads]

    async def create(self, data: TriggerCreate, owner: UserDB) -> TriggerResponse:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to create a trigger")
        await self._validate_team_ids(data.team_ids)
        validate_visibility(data.visibility, data.team_ids)
        project, _ = await ProjectService(
            self.db, self.workspace_id
        ).validate_placement(
            data.project_id,
            data.folder_id,
            owner,
            lock_project=data.project_id is not None,
        )
        if data.trigger_type == TriggerType.schedule:
            if data.cron_expression is None or data.timezone is None:
                raise DomainValidationError(
                    "Scheduled triggers require a schedule and timezone"
                )
            ensure_valid_schedule(data.cron_expression, data.timezone)
        # Fail at save time, not first fire — 409 model_unavailable on the form.
        await self.model_service.ensure_available(data.model_id)
        await ModelService.validate_reasoning_effort(
            data.model_id, data.reasoning_effort
        )
        await self._ensure_agent_usable(data.agent_id, owner, self.workspace_id)
        audience_visibility = (
            project.visibility if project is not None else data.visibility
        )
        audience_owner_id = project.owner_id if project is not None else owner.id
        audience_team_ids = (
            await ProjectRepository(self.db, self.workspace_id).list_team_ids(
                project.id
            )
            if project is not None and project.visibility == ResourceVisibility.teams
            else data.team_ids
            if project is None
            else []
        )
        await self._ensure_agent_scope(
            data.agent_id,
            visibility=audience_visibility,
            owner_id=audience_owner_id,
            team_ids=audience_team_ids,
            trigger_owner_id=owner.id,
        )
        normalized_resources = await self._normalize_resource_selection(
            data.agent_id,
            {
                field: getattr(data, field)
                for field in (*_RESOURCE_FIELDS, _TOOL_RESOURCE_FIELD)
                if getattr(data, field) is not None
            },
            project_id=data.project_id,
        )
        next_run_at = (
            compute_next_run_at(
                data.cron_expression, data.timezone, after=datetime.now(UTC)
            )
            if data.trigger_type == TriggerType.schedule and data.is_active
            else None
        )
        trigger = await self.repository.create(
            TriggerCreateDB(
                **data.model_dump(exclude={*_RESOURCE_FIELDS, _TOOL_RESOURCE_FIELD}),
                **normalized_resources,
                workspace_id=self.workspace_id,
                owner_id=owner.id,
                webhook_id=(
                    uuid4() if data.trigger_type == TriggerType.webhook else None
                ),
                next_run_at=next_run_at,
            )
        )
        if data.team_ids:
            await self.repository.set_team_ids(trigger.id, data.team_ids)
        response = (await self._to_responses([trigger], owner))[0]
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.triggers,
        )
        if trigger.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return response

    async def update(
        self, trigger_id: UUID, data: TriggerPatch, user: UserDB
    ) -> TriggerResponse:
        trigger = await self.repository.get_for_update(trigger_id)
        if trigger is None:
            raise NotFoundError("Trigger not found")
        self._ensure_can_manage(trigger, user)
        previous_project_id = trigger.project_id
        if trigger.project_id is not None and (
            "visibility" in data.model_fields_set or "team_ids" in data.model_fields_set
        ):
            raise DomainValidationError(
                "Detach the trigger before changing its direct visibility"
            )
        update_data = data.model_dump(exclude_unset=True)
        next_project_id = (
            data.project_id
            if "project_id" in data.model_fields_set
            else trigger.project_id
        )
        if (
            "project_id" in data.model_fields_set
            and next_project_id != trigger.project_id
            and "folder_id" not in data.model_fields_set
        ):
            data = data.model_copy(update={"folder_id": None})
            data.model_fields_set.add("folder_id")
            update_data = data.model_dump(exclude_unset=True)
        next_folder_id = (
            data.folder_id
            if "folder_id" in data.model_fields_set
            else trigger.folder_id
        )
        project, _ = await ProjectService(
            self.db, trigger.workspace_id
        ).validate_placement(
            next_project_id,
            next_folder_id,
            user,
            lock_project=next_project_id is not None,
        )
        next_visibility = data.visibility or trigger.visibility
        next_team_ids = (
            data.team_ids
            if data.team_ids is not None
            else (
                await self.repository.list_team_ids(trigger.id)
                if trigger.visibility == ResourceVisibility.teams
                else []
            )
        )
        await self._validate_team_ids(next_team_ids)
        validate_visibility(next_visibility, next_team_ids)
        effective_visibility = (
            project.visibility if project is not None else next_visibility
        )
        effective_owner_id = (
            project.owner_id if project is not None else trigger.owner_id
        )
        effective_team_ids = (
            await ProjectRepository(self.db, trigger.workspace_id).list_team_ids(
                project.id
            )
            if project is not None and project.visibility == ResourceVisibility.teams
            else next_team_ids
            if project is None
            else []
        )
        await self._ensure_agent_scope(
            data.agent_id or trigger.agent_id,
            visibility=effective_visibility,
            owner_id=effective_owner_id,
            team_ids=effective_team_ids,
            trigger_owner_id=trigger.owner_id,
        )

        if trigger.trigger_type == TriggerType.webhook and (
            "cron_expression" in update_data or "timezone" in update_data
        ):
            raise DomainValidationError("Webhook triggers do not have a schedule")

        cron = update_data.get("cron_expression", trigger.cron_expression)
        timezone = update_data.get("timezone", trigger.timezone)
        schedule_changed = (
            cron != trigger.cron_expression or timezone != trigger.timezone
        )
        if schedule_changed and trigger.trigger_type == TriggerType.schedule:
            if not cron or not timezone:
                raise DomainValidationError(
                    "Scheduled triggers require a schedule and timezone"
                )
            ensure_valid_schedule(cron, timezone)
        if "model_id" in update_data:
            await self.model_service.ensure_available(update_data["model_id"])
        clear_stale_effort = False
        if "reasoning_effort" in update_data:
            # A fresh user choice is validated strictly against the model
            # that will be stored.
            await ModelService.validate_reasoning_effort(
                update_data.get("model_id", trigger.model_id),
                update_data["reasoning_effort"],
            )
        elif "model_id" in update_data and trigger.reasoning_effort is not None:
            # Re-pointing the model with a carried-over effort the new model
            # doesn't declare must not block the edit (the stored value was
            # valid when saved) — clear it back to the model default, the
            # same clamp ensure_available applies at run time.
            clear_stale_effort = not await ModelService.is_reasoning_effort_declared(
                update_data["model_id"], trigger.reasoning_effort
            )
        agent_changed = (
            "agent_id" in update_data and update_data["agent_id"] != trigger.agent_id
        )
        all_resource_fields = (*_RESOURCE_FIELDS, _TOOL_RESOURCE_FIELD)
        resource_fields_set = set(data.model_fields_set) & set(all_resource_fields)
        resource_selection = {
            field: getattr(data, field)
            for field in all_resource_fields
            if field in resource_fields_set
        }
        if agent_changed:
            # A selection belongs to one agent graph. Fields the caller did not
            # explicitly choose reset to inheritance when the agent changes.
            resource_selection = {
                field: getattr(data, field) if field in resource_fields_set else None
                for field in all_resource_fields
            }
        if resource_selection:
            data = data.model_copy(
                update=await self._normalize_resource_selection(
                    update_data.get("agent_id", trigger.agent_id),
                    resource_selection,
                    project_id=next_project_id,
                )
            )
        reactivating = data.is_active is True and not trigger.is_active
        if agent_changed or reactivating:
            # Check against the owner, not the caller — an admin may edit
            # someone else's trigger, but the run still executes as the owner.
            owner = (
                user if user.id == trigger.owner_id else await self._get_owner(trigger)
            )
            await self._ensure_agent_usable(
                update_data.get("agent_id", trigger.agent_id),
                owner,
                trigger.workspace_id,
            )

        trigger = await self.repository.update(trigger, data)
        if data.team_ids is not None:
            await self.repository.set_team_ids(trigger.id, data.team_ids)

        if clear_stale_effort:
            trigger.reasoning_effort = None
            self.db.add(trigger)
            await self.db.flush()

        # Rematerialize the schedule: pausing clears next_run_at so the row
        # drops out of the due scan; (re)activating or editing the schedule
        # recomputes from now — missed occurrences are skipped, not replayed.
        if not trigger.is_active or trigger.trigger_type == TriggerType.webhook:
            next_run_at = None
        elif schedule_changed or trigger.next_run_at is None:
            if cron is None or timezone is None:
                raise DomainValidationError(
                    "Scheduled triggers require a schedule and timezone"
                )
            next_run_at = compute_next_run_at(cron, timezone, after=datetime.now(UTC))
        else:
            next_run_at = trigger.next_run_at
        if trigger.next_run_at != next_run_at:
            trigger.next_run_at = next_run_at
            self.db.add(trigger)
            await self.db.flush()
            await self.db.refresh(trigger)
        # Recompute availability: a patch that doesn't touch model_id (e.g.
        # pause/resume) must not reset the flag to its default on the client.
        response = (await self._to_responses([trigger], user))[0]
        await stage_workspace_event(
            self.db,
            workspace_id=trigger.workspace_id,
            kind=WorkspaceEventKind.triggers,
        )
        if previous_project_id is not None or trigger.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=trigger.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return response

    async def _ensure_visible(self, trigger: TriggerDB, user: UserDB) -> None:
        _, visibility, owner_id, team_ids = await self._effective_audience(trigger)
        if trigger.owner_id != user.id and not is_resource_visible(
            visibility=visibility,
            owner_id=owner_id,
            team_ids=team_ids,
            user=user,
        ):
            raise NotFoundError("Trigger not found")

    async def _validate_team_ids(self, team_ids: list[UUID]) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        for team_id in set(team_ids):
            if (
                await self.teams.get_in_workspace_for_key_share(
                    team_id, self.workspace_id
                )
                is None
            ):
                raise NotFoundError("Team not found")

    async def delete(self, trigger_id: UUID, user: UserDB) -> None:
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)
        await self.repository.delete(trigger)
        await stage_workspace_event(
            self.db,
            workspace_id=trigger.workspace_id,
            kind=WorkspaceEventKind.triggers,
        )
        if trigger.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=trigger.workspace_id,
                kind=WorkspaceEventKind.projects,
            )

    async def run_now(self, trigger_id: UUID, user: UserDB) -> TriggerRunResponse:
        """Fire one occurrence immediately — the test path behind a "Run now"
        button. Works on paused triggers and leaves the schedule untouched
        (`next_run_at` / `last_run_at` track scheduled fires only).

        The run executes as the trigger *owner* (their MCP credentials), even
        when an admin presses the button — exactly as a scheduled firing would.
        Commits before enqueueing, same choreography as ``claim_and_enqueue``:
        the worker reads the thread from its own session, so the row must be
        committed before the run is dispatched.
        """
        trigger = await self.repository.get_for_update(trigger_id)
        if trigger is None:
            raise NotFoundError("Trigger not found")
        self._ensure_can_manage(trigger, user)
        owner = await self._get_owner(trigger)
        await self._ensure_project_visible_to_owner(trigger, owner)
        await self._ensure_agent_usable(trigger.agent_id, owner, trigger.workspace_id)
        agent = await AgentService(self.db, trigger.workspace_id).repository.get_scoped(
            trigger.agent_id
        )
        if agent is None or agent.is_archived:
            raise DomainValidationError("Trigger agent is archived or deleted")
        # Before creating the fire thread — RunService.create would reject the
        # run anyway, but this keeps a doomed request from leaving an orphan
        # thread behind.
        await self.model_service.ensure_available(trigger.model_id)
        thread = await self._create_fire_thread(trigger)
        await self.db.commit()
        record = await RunService().create(
            thread_id=thread.id,
            user_id=str(trigger.owner_id),
            input={"messages": [{"type": "human", "content": trigger.instructions}]},
        )
        return TriggerRunResponse(thread_id=thread.id, run_id=record.id)

    async def invoke_webhook(
        self, webhook_id: UUID, data: WebhookTriggerInvoke
    ) -> TriggerRunResponse:
        """Resolve webhook overrides and atomically create its thread and run."""
        trigger = await self.repository.get_by_webhook_id_for_update(webhook_id)
        if trigger is None or not trigger.is_active:
            # Keep inactive and unknown webhook URLs indistinguishable to
            # unauthenticated callers.
            raise NotFoundError("Webhook not found")

        owner = await self._get_owner(trigger)
        await self._ensure_project_visible_to_owner(trigger, owner)
        agent_id = data.agent_id or trigger.agent_id
        model_id = data.model_id if data.model_id is not None else trigger.model_id
        instructions = (
            data.instructions if data.instructions is not None else trigger.instructions
        )
        if not instructions.strip():
            raise DomainValidationError("Webhook instructions cannot be empty")

        await self._ensure_agent_usable(agent_id, owner, trigger.workspace_id)
        _, visibility, owner_id, team_ids = await self._effective_audience(trigger)
        await self._ensure_agent_scope(
            agent_id,
            visibility=visibility,
            owner_id=owner_id,
            team_ids=list(team_ids),
            trigger_owner_id=owner.id,
        )
        agent = await AgentService(self.db, trigger.workspace_id).repository.get_scoped(
            agent_id
        )
        if agent is None or agent.is_archived:
            raise DomainValidationError("Webhook agent is archived or deleted")
        await ModelService(self.db, trigger.workspace_id).ensure_available(model_id)

        reasoning_effort = (
            trigger.reasoning_effort if model_id == trigger.model_id else None
        )
        thread = await self._create_fire_thread(
            trigger,
            agent_id=agent_id,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
        )
        record = await RunService().create_in_session(
            self.db,
            thread_id=thread.id,
            user_id=str(trigger.owner_id),
            input={"messages": [{"type": "human", "content": instructions}]},
        )
        trigger.last_run_at = datetime.now(UTC)
        self.db.add(trigger)
        await self.db.flush()
        return TriggerRunResponse(thread_id=thread.id, run_id=record.id)

    async def _create_fire_thread(
        self,
        trigger: TriggerDB,
        *,
        agent_id: UUID | None = None,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
    ):
        """One fresh thread per firing, owned by the trigger owner."""
        effective_agent_id = agent_id or trigger.agent_id
        resource_selection = (
            {
                field: [UUID(resource_id) for resource_id in value]
                for field in _RESOURCE_FIELDS
                if (value := getattr(trigger, field, None)) is not None
            }
            if effective_agent_id == trigger.agent_id
            else {}
        )
        if (
            effective_agent_id == trigger.agent_id
            and trigger.disabled_mcp_tools is not None
        ):
            resource_selection[_TOOL_RESOURCE_FIELD] = {
                UUID(server_id): tool_names
                for server_id, tool_names in trigger.disabled_mcp_tools.items()
            }
        return await ThreadService(self.db, trigger.workspace_id).create(
            ThreadCreate(
                agent_id=effective_agent_id,
                project_id=trigger.project_id,
                folder_id=trigger.folder_id,
                model_id=model_id or trigger.model_id,
                reasoning_effort=(
                    trigger.reasoning_effort
                    if reasoning_effort is None and model_id is None
                    else reasoning_effort
                ),
                first_message_content=trigger.name,
                **resource_selection,
            ),
            user_id=trigger.owner_id,
            source=ThreadSource.trigger,
            trigger_id=trigger.id,
        )

    # ------------------------------------------------------------------
    # Scanner entrypoint
    # ------------------------------------------------------------------

    async def claim_and_enqueue(self, now: datetime | None = None) -> list[str]:
        """One scanner tick: claim due triggers, advance their schedule, create
        one thread per firing, then enqueue the runs. Returns the enqueued
        run ids.

        Commits the claim itself (Postgres claim and Redis enqueue are not one
        transaction), so it must run on a dedicated session — the scanner's —
        never inside a request-scoped transaction. Committing *before*
        enqueueing means a crash in between skips that occurrence instead of
        double-running it; the advanced ``next_run_at`` keeps the next one on
        schedule.
        """
        now = now or datetime.now(UTC)
        # Warm the whitelist cache *before* the claim, exactly as
        # `RunService.create` does and for a sharper version of the same reason:
        # `is_available` below runs inside this transaction, which holds
        # `FOR UPDATE SKIP LOCKED` locks on every claimed trigger row. A cold or
        # expired catalog cache makes that a multi-second CDN fetch with those
        # locks held (design review §3.7).
        await ModelService.list_whitelisted()
        claimed = await self.repository.claim_due(
            now, limit=trigger_settings.claim_batch_size
        )
        launches: list[tuple[str, str, str]] = []  # (thread_id, owner_id, message)
        for trigger in claimed:
            try:
                owner = await self._get_owner(trigger)
                await self._ensure_project_visible_to_owner(trigger, owner)
                await self._ensure_agent_usable(
                    trigger.agent_id, owner, trigger.workspace_id
                )
            except (DomainValidationError, NotFoundError, PermissionDeniedError):
                logger.warning(
                    "Pausing trigger %s: its owner can no longer access its "
                    "project or agent %s",
                    trigger.id,
                    trigger.agent_id,
                )
                trigger.is_active = False
                trigger.next_run_at = None
                self.db.add(trigger)
                continue
            agent = await AgentService(
                self.db, trigger.workspace_id
            ).repository.get_scoped(trigger.agent_id)
            if agent is None or agent.is_archived:
                logger.warning(
                    "Pausing trigger %s: agent %s is archived or gone",
                    trigger.id,
                    trigger.agent_id,
                )
                trigger.is_active = False
                trigger.next_run_at = None
                self.db.add(trigger)
                continue
            try:
                if not trigger.cron_expression or not trigger.timezone:
                    raise ValueError("scheduled trigger is missing its schedule")
                trigger.next_run_at = compute_next_run_at(
                    trigger.cron_expression, trigger.timezone, after=now
                )
            except Exception:
                logger.exception(
                    "Pausing trigger %s: schedule no longer computes", trigger.id
                )
                trigger.is_active = False
                trigger.next_run_at = None
                self.db.add(trigger)
                continue
            if not await ModelService(self.db, trigger.workspace_id).is_available(
                trigger.model_id
            ):
                # Skip the firing but keep the schedule advancing (mirrors the
                # missed-run policy); the trigger recovers by itself when an
                # admin re-enables the model. `last_run_at` tracks actual
                # fires, so it is not stamped for a skip.
                logger.warning(
                    "Skipping trigger %s: model %s is not available",
                    trigger.id,
                    trigger.model_id,
                )
                self.db.add(trigger)
                continue
            trigger.last_run_at = now
            self.db.add(trigger)
            thread = await self._create_fire_thread(trigger)
            launches.append((thread.id, str(trigger.owner_id), trigger.instructions))
        await self.db.commit()  # finish the claim, release the row locks

        run_service = RunService()
        run_ids: list[str] = []
        for thread_id, owner_id, message in launches:
            try:
                record = await run_service.create(
                    thread_id=thread_id,
                    user_id=owner_id,
                    input={"messages": [{"type": "human", "content": message}]},
                )
            except Exception:
                logger.exception("Failed to enqueue run for thread %s", thread_id)
                continue
            run_ids.append(record.id)
        return run_ids


def get_trigger_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> TriggerService:
    return TriggerService(db, workspace_id)
