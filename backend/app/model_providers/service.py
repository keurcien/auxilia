"""ModelService — the single definition of "is this model usable right now".

A model is available iff it is in the whitelist AND its serving provider has
an API key configured AND a workspace admin has enabled it (row in `models`
with is_enabled=true; row absent = disabled). Every consumer goes through
this service: the run-creation gate, Agent.build's backstop, trigger
create/update, the picker endpoint, and the thread response's
`model_available` flag.
"""

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    ModelUnavailableError,
    NotFoundError,
)
from app.model_providers.catalog import provider_api_keys
from app.model_providers.models import ModelDB
from app.model_providers.repository import ModelRepository
from app.model_providers.schemas import (
    ManagedModelResponse,
    ModelCreateDB,
    WhitelistSyncResponse,
)
from app.model_providers.whitelist import (
    SupportedModel,
    get_whitelist,
    sync_whitelist,
)
from app.service import BaseService


class ResolvedModel(BaseModel):
    """An available model plus what Agent.build needs to instantiate it."""

    provider: str
    model_id: str
    api_key: str


def _managed(entry: SupportedModel | None, row: ModelDB) -> ManagedModelResponse:
    """Project an enablement row (plus its whitelist entry, if it still has
    one) into the admin Settings shape."""
    return ManagedModelResponse(
        provider=row.provider,
        model_id=row.model_id,
        display_name=entry.display_name if entry else row.model_id,
        chef=entry.chef if entry else row.provider.capitalize(),
        chef_slug=entry.chef_slug if entry else row.provider,
        multimodal=entry.multimodal if entry else False,
        supports_structured_output=(
            entry.supports_structured_output if entry else False
        ),
        is_enabled=row.is_enabled,
        is_default=row.is_default,
        deprecated=entry is None,
    )


class ModelService(BaseService[ModelDB, ModelRepository]):
    not_found_message = "Model not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, ModelRepository(db))

    async def _enabled_keys(self) -> set[tuple[str, str]]:
        rows = await self.repository.list_all()
        return {(r.provider, r.model_id) for r in rows if r.is_enabled}

    async def list_available(self) -> list[SupportedModel]:
        """The models users may pick: whitelist ∧ provider key ∧ admin-enabled."""
        whitelist = await get_whitelist()
        keys = provider_api_keys()
        enabled = await self._enabled_keys()
        return [
            m
            for m in whitelist
            if m.provider in keys and (m.provider, m.model_id) in enabled
        ]

    async def ensure_available(self, model_id: str | None) -> ResolvedModel:
        """The chokepoint: raise ModelUnavailableError with the precise reason,
        or return what ChatModelFactory needs. Called by RunService.create
        (the pre-stream gate), Agent.build (the backstop) and TriggerService."""
        if not model_id:
            raise ModelUnavailableError("", "no model is set")
        whitelist = await get_whitelist()
        entry = next((m for m in whitelist if m.model_id == model_id), None)
        if entry is None:
            raise ModelUnavailableError(
                model_id, "it is not in the supported model catalog"
            )
        api_key = provider_api_keys().get(entry.provider)
        if not api_key:
            raise ModelUnavailableError(
                model_id,
                f"provider '{entry.provider}' has no API key configured",
            )
        row = await self.repository.get_by_provider_and_model_id(
            entry.provider, entry.model_id
        )
        if row is None or not row.is_enabled:
            raise ModelUnavailableError(
                model_id, "it has been disabled by a workspace admin"
            )
        return ResolvedModel(
            provider=entry.provider, model_id=entry.model_id, api_key=api_key
        )

    @staticmethod
    async def list_whitelisted() -> list[SupportedModel]:
        """The full whitelist, ignoring availability — for labeling models
        that are disabled or keyless (e.g. a trigger pinned to a model an
        admin turned off). Models that left the whitelist entirely appear
        nowhere; callers fall back to the raw id."""
        return await get_whitelist()

    async def is_available(self, model_id: str | None) -> bool:
        try:
            await self.ensure_available(model_id)
        except ModelUnavailableError:
            return False
        return True

    async def list_manage(self) -> list[ManagedModelResponse]:
        """The admin view: every whitelist model whose provider has a key,
        with its enablement state, plus orphan rows whose model has left the
        whitelist (flagged deprecated so admins understand blocked threads)."""
        whitelist = await get_whitelist()
        keys = provider_api_keys()
        rows = {(r.provider, r.model_id): r for r in await self.repository.list_all()}

        managed = [
            ManagedModelResponse(
                provider=m.provider,
                model_id=m.model_id,
                display_name=m.display_name,
                chef=m.chef,
                chef_slug=m.chef_slug,
                multimodal=m.multimodal,
                supports_structured_output=m.supports_structured_output,
                is_enabled=(row := rows.get((m.provider, m.model_id))) is not None
                and row.is_enabled,
                is_default=row is not None and row.is_default,
            )
            for m in whitelist
            if m.provider in keys
        ]
        whitelisted = {(m.provider, m.model_id) for m in whitelist}
        managed.extend(
            _managed(None, row)
            for key, row in sorted(rows.items())
            if key not in whitelisted
        )
        return managed

    async def set_enabled(
        self, provider: str, model_id: str, is_enabled: bool
    ) -> ManagedModelResponse:
        whitelist = await get_whitelist()
        entry = next(
            (m for m in whitelist if m.provider == provider and m.model_id == model_id),
            None,
        )
        if entry is None:
            # Orphan rows (model left the whitelist) may still be toggled off,
            # never on — re-enabling something unservable makes no sense.
            row = await self.repository.get_by_provider_and_model_id(provider, model_id)
            if row is None or is_enabled:
                raise NotFoundError("Model not found in the supported catalog")
        if not is_enabled:
            remaining = [
                m
                for m in await self.list_available()
                if not (m.provider == provider and m.model_id == model_id)
            ]
            if not remaining:
                raise DomainValidationError(
                    "Cannot disable the last available model in the workspace."
                )

        # Locked so a concurrent set_default can't re-flag the row between
        # this read and the auto-unset below.
        row = await self.repository.get_by_provider_and_model_id(
            provider, model_id, for_update=True
        )
        if row is None:
            row = await self.repository.create(
                ModelCreateDB(
                    provider=provider, model_id=model_id, is_enabled=is_enabled
                )
            )
        else:
            changed = row.is_enabled != is_enabled
            row.is_enabled = is_enabled
            # Disabling the workspace default silently returns the workspace
            # to "automatic" — the default must always be a usable model.
            if not is_enabled and row.is_default:
                row.is_default = False
                changed = True
            if changed:
                self.db.add(row)
                await self.db.flush()
                await self.db.refresh(row)

        return _managed(entry, row)

    async def set_default(self, provider: str, model_id: str) -> ManagedModelResponse:
        """Flag one model as the workspace default. It must be available right
        now (whitelist ∧ provider key ∧ enabled) — ensure_available raises the
        precise reason otherwise."""
        resolved = await self.ensure_available(model_id)
        if resolved.provider != provider:
            raise NotFoundError("Model not found in the supported catalog")

        # Lock the target row and revalidate under the lock: concurrent admin
        # mutations could otherwise persist a disabled model as the default
        # (racing set_enabled) or trip the single-default unique index with a
        # raw 500 (racing another set_default).
        row = await self.repository.get_by_provider_and_model_id(
            provider, model_id, for_update=True
        )
        if row is None or not row.is_enabled:
            raise ModelUnavailableError(
                model_id, "it has been disabled by a workspace admin"
            )

        current = await self.repository.get_default(for_update=True)
        if current and (current.provider, current.model_id) != (provider, model_id):
            current.is_default = False
            self.db.add(current)
            # Flush the unset before the set so the partial unique index never
            # sees two default rows.
            await self.db.flush()

        if not row.is_default:
            row.is_default = True
            self.db.add(row)
            await self.db.flush()
            await self.db.refresh(row)

        whitelist = await get_whitelist()
        entry = next(
            (m for m in whitelist if m.provider == provider and m.model_id == model_id),
            None,
        )
        return _managed(entry, row)

    async def clear_default(self) -> None:
        """Back to automatic: consumers fall back to the first available model."""
        row = await self.repository.get_default(for_update=True)
        if row is not None:
            row.is_default = False
            self.db.add(row)
            await self.db.flush()

    async def get_default_model_id(
        self, available: list[SupportedModel] | None = None
    ) -> str | None:
        """The effective workspace default: the admin-flagged model while it is
        still available, else the first available model, else None. Every
        consumer that needs a model without the user picking one (Slack
        threads, picker preselection) resolves through here. Callers that
        already hold ``list_available()``'s result pass it in to skip a second
        resolution."""
        if available is None:
            available = await self.list_available()
        if not available:
            return None
        row = await self.repository.get_default()
        if row and any(
            m.provider == row.provider and m.model_id == row.model_id for m in available
        ):
            return row.model_id
        return available[0].model_id

    @staticmethod
    async def sync() -> WhitelistSyncResponse:
        return WhitelistSyncResponse(**await sync_whitelist())


def get_model_service(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db)
