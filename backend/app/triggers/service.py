from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB
from app.agents.runs.service import RunService
from app.database import get_db
from app.exceptions import DomainValidationError, PermissionDeniedError
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.model_providers.catalog import MODELS
from app.service import BaseService
from app.threads.models import ThreadSource
from app.threads.schemas import ThreadCreate
from app.threads.service import ThreadService
from app.triggers.models import TriggerDB
from app.triggers.repository import TriggerRepository
from app.triggers.schedule import compute_next_run_at, ensure_valid_schedule
from app.triggers.schemas import (
    TriggerCreate,
    TriggerCreateDB,
    TriggerPatch,
    TriggerResponse,
    TriggerRunResponse,
    TriggerThreadResponse,
)
from app.triggers.settings import trigger_settings
from app.users.models import UserDB, WorkspaceRole


logger = logging.getLogger(__name__)


class TriggerService(BaseService[TriggerDB, TriggerRepository]):
    not_found_message = "Trigger not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, TriggerRepository(db))
        self.agent_service = AgentService(db)
        self.thread_service = ThreadService(db)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_can_manage(trigger: TriggerDB, user: UserDB) -> None:
        if trigger.owner_id != user.id and user.role != WorkspaceRole.admin:
            raise PermissionDeniedError("Not authorized to access this trigger")

    @staticmethod
    def _ensure_known_model(model_id: str) -> None:
        if model_id not in {m.name for m in MODELS}:
            raise DomainValidationError(f"Unknown model: {model_id}")

    async def _ensure_agent_usable(self, agent_id: UUID, owner: UserDB) -> None:
        """The trigger's agent must be one its *owner* is allowed to use —
        runs execute with the owner's identity and MCP credentials."""
        agent = await self.agent_service.get(
            agent_id,
            user_id=owner.id,
            user_role=owner.role,
            user_team_id=owner.team_id,
        )
        if agent.current_user_permission is None:
            raise PermissionDeniedError(
                "Trigger owner is not allowed to use this agent"
            )

    async def _get_owner(self, trigger: TriggerDB) -> UserDB:
        owner = await self.db.get(UserDB, trigger.owner_id)
        if owner is None:  # FK guarantees this in practice
            raise DomainValidationError("Trigger owner no longer exists")
        return owner

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list(self, user: UserDB) -> list[TriggerResponse]:
        if user.role == WorkspaceRole.admin:
            triggers = await self.repository.list_all()
        else:
            triggers = await self.repository.list_for_owner(user.id)
        return [TriggerResponse.model_validate(t) for t in triggers]

    async def get(self, trigger_id: UUID, user: UserDB) -> TriggerResponse:
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)
        return TriggerResponse.model_validate(trigger)

    async def list_threads(
        self, trigger_id: UUID, user: UserDB
    ) -> list[TriggerThreadResponse]:
        """Past firings (one thread per firing), last 30 days, newest first."""
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)
        since = datetime.now(UTC) - timedelta(days=30)
        threads = await self.thread_service.list_for_trigger(trigger_id, since=since)
        return [TriggerThreadResponse.model_validate(t) for t in threads]

    async def create(self, data: TriggerCreate, owner: UserDB) -> TriggerResponse:
        ensure_valid_schedule(data.cron_expression, data.timezone)
        self._ensure_known_model(data.model_id)
        await self._ensure_agent_usable(data.agent_id, owner)
        next_run_at = (
            compute_next_run_at(
                data.cron_expression, data.timezone, after=datetime.now(UTC)
            )
            if data.is_active
            else None
        )
        trigger = await self.repository.create(
            TriggerCreateDB(
                **data.model_dump(), owner_id=owner.id, next_run_at=next_run_at
            )
        )
        return TriggerResponse.model_validate(trigger)

    async def update(
        self, trigger_id: UUID, data: TriggerPatch, user: UserDB
    ) -> TriggerResponse:
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)

        update_data = data.model_dump(exclude_unset=True)
        cron = update_data.get("cron_expression", trigger.cron_expression)
        timezone = update_data.get("timezone", trigger.timezone)
        schedule_changed = (
            cron != trigger.cron_expression or timezone != trigger.timezone
        )
        if schedule_changed:
            ensure_valid_schedule(cron, timezone)
        if "model_id" in update_data:
            self._ensure_known_model(update_data["model_id"])
        if "agent_id" in update_data and update_data["agent_id"] != trigger.agent_id:
            # Check against the owner, not the caller — an admin may edit
            # someone else's trigger, but the run still executes as the owner.
            owner = (
                user if user.id == trigger.owner_id else await self._get_owner(trigger)
            )
            await self._ensure_agent_usable(update_data["agent_id"], owner)

        trigger = await self.repository.update(trigger, data)

        # Rematerialize the schedule: pausing clears next_run_at so the row
        # drops out of the due scan; (re)activating or editing the schedule
        # recomputes from now — missed occurrences are skipped, not replayed.
        if not trigger.is_active:
            next_run_at = None
        elif schedule_changed or trigger.next_run_at is None:
            next_run_at = compute_next_run_at(cron, timezone, after=datetime.now(UTC))
        else:
            next_run_at = trigger.next_run_at
        if trigger.next_run_at != next_run_at:
            trigger.next_run_at = next_run_at
            self.db.add(trigger)
            await self.db.flush()
            await self.db.refresh(trigger)
        return TriggerResponse.model_validate(trigger)

    async def delete(self, trigger_id: UUID, user: UserDB) -> None:
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)
        await self.repository.delete(trigger)

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
        trigger = await self.get_or_404(trigger_id)
        self._ensure_can_manage(trigger, user)
        agent = await self.db.get(AgentDB, trigger.agent_id)
        if agent is None or agent.is_archived:
            raise DomainValidationError("Trigger agent is archived or deleted")
        # Probe the OWNER's credentials (the run executes as them, even when an
        # admin presses the button) via the shared pre-flight gate, so a broken
        # OAuth fails the request with an actionable message instead of a
        # doomed run. Scheduled firings get the same protection from the
        # worker's pre-flight (`_mcp_unauthorized`).
        try:
            await RunService.ensure_mcp_authorized(
                self.db, trigger.agent_id, str(trigger.owner_id)
            )
        except OAuthAuthorizationRequired as exc:
            raise DomainValidationError(
                "The trigger owner must reconnect this agent's MCP servers "
                "(from the agent's chat page) before it can run."
            ) from exc
        thread = await self._create_fire_thread(trigger)
        await self.db.commit()
        record = await RunService().create(
            thread_id=thread.id,
            user_id=str(trigger.owner_id),
            input={"messages": [{"type": "human", "content": trigger.instructions}]},
        )
        return TriggerRunResponse(thread_id=thread.id, run_id=record.id)

    async def _create_fire_thread(self, trigger: TriggerDB):
        """One fresh thread per firing, owned by the trigger owner."""
        return await self.thread_service.create(
            ThreadCreate(
                agent_id=trigger.agent_id,
                model_id=trigger.model_id,
                first_message_content=trigger.name,
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
        claimed = await self.repository.claim_due(
            now, limit=trigger_settings.claim_batch_size
        )
        launches: list[tuple[str, str, str]] = []  # (thread_id, owner_id, message)
        for trigger in claimed:
            agent = await self.db.get(AgentDB, trigger.agent_id)
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
                trigger.next_run_at = compute_next_run_at(
                    trigger.cron_expression, trigger.timezone, after=now
                )
            except Exception:  # noqa: BLE001 — a poison schedule must not wedge the scan
                logger.exception(
                    "Pausing trigger %s: schedule no longer computes", trigger.id
                )
                trigger.is_active = False
                trigger.next_run_at = None
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
            except Exception:  # noqa: BLE001 — one bad enqueue must not stop the rest
                logger.exception("Failed to enqueue run for thread %s", thread_id)
                continue
            run_ids.append(record.id)
        return run_ids


def get_trigger_service(db: AsyncSession = Depends(get_db)) -> TriggerService:
    return TriggerService(db)
