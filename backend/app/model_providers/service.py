"""ModelService — the single definition of "is this model usable right now".

A model is available iff it is in the whitelist AND its serving provider has
an API key configured AND a workspace admin has enabled it (row in `models`
with is_enabled=true; row absent = disabled). Every consumer goes through
this service: the run-creation gate, Agent.build's backstop, trigger
create/update, the picker endpoint, and the thread response's
`model_available` flag.
"""

import logging
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    ModelUnavailableError,
    NotFoundError,
)
from app.model_providers.catalog import GOOGLE_ADC_SENTINEL, provider_api_keys
from app.model_providers.models import (
    ModelDB,
    ModelProviderCatalogEntryDB,
    ModelProviderType,
)
from app.model_providers.ollama import (
    DiscoveredOllamaModel,
    discover_ollama_models,
    validate_ollama_url,
)
from app.model_providers.repository import (
    ModelProviderCatalogRepository,
    ModelProviderCredentialRepository,
    ModelRepository,
)
from app.model_providers.schemas import (
    ManagedModelResponse,
    ModelCreateDB,
    ModelProviderConfigResponse,
    OllamaDiscoveryResponse,
    ProviderConfigurationType,
    ProviderCredentialSource,
    WhitelistSyncResponse,
)
from app.model_providers.whitelist import (
    SupportedModel,
    get_whitelist,
    sync_whitelist,
)
from app.service import BaseService
from app.workspaces.dependencies import get_active_workspace_id


logger = logging.getLogger(__name__)


class ResolvedModel(BaseModel):
    """An available model plus what Agent.build needs to instantiate it."""

    provider: str
    model_id: str
    runtime_model_id: str
    api_key: str | None = None
    base_url: str | None = None
    # The effort to send: the thread's choice clamped to the whitelist
    # entry's declared levels, else the entry's applied default. None = the
    # model declares no default — send nothing, provider default applies.
    reasoning_effort: str | None = None
    # The cheapest declared level (the ladder's first entry), for internal
    # routing calls that need speed over depth. None = no effort knob.
    minimal_reasoning_effort: str | None = None
    supports_web_search: bool = False
    supports_tool_search: bool = False
    context_window: int | None = None


def _managed(entry: SupportedModel | None, row: ModelDB) -> ManagedModelResponse:
    """Project an enablement row (plus its whitelist entry, if it still has
    one) into the admin Settings shape."""
    return ManagedModelResponse(
        prices=entry.prices if entry else None,
        provider=row.provider,
        model_id=row.model_id,
        display_name=entry.display_name if entry else row.model_id,
        chef=entry.chef if entry else row.provider.capitalize(),
        chef_slug=entry.chef_slug if entry else row.provider,
        multimodal=entry.multimodal if entry else False,
        supports_structured_output=(
            entry.supports_structured_output if entry else False
        ),
        supports_tools=entry.supports_tools if entry else False,
        is_available=entry.is_available if entry else False,
        is_enabled=row.is_enabled,
        is_default=row.is_default,
        is_quick=row.is_quick,
        deprecated=entry is None or not entry.is_available,
    )


def _catalog_entry(row: ModelProviderCatalogEntryDB) -> SupportedModel:
    # Early Ollama discovery stored Qwen under Alibaba's vendor slug. Keep
    # existing rows visually correct without requiring a fresh discovery.
    chef_slug = "qwen" if row.chef.lower() == "qwen" else row.chef_slug
    return SupportedModel(
        provider=row.provider,
        model_id=row.model_id,
        runtime_model_id=row.runtime_model_id,
        display_name=row.display_name,
        chef=row.chef,
        chef_slug=chef_slug,
        multimodal=row.multimodal,
        supports_structured_output=row.supports_structured_output,
        supports_tools=row.supports_tools,
        is_available=row.is_available,
        supports_web_search=False,
        supports_tool_search=False,
    )


class ModelService(BaseService[ModelDB, ModelRepository]):
    not_found_message = "Model not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, ModelRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.credential_repository = ModelProviderCredentialRepository(db, workspace_id)
        self.catalog_repository = ModelProviderCatalogRepository(db, workspace_id)

    async def _provider_api_keys(self) -> dict[str, str]:
        """Resolve credentials with encrypted DB values taking precedence.

        Environment values remain a deployment migration fallback. Google ADC
        is not an API key and remains available when the runtime identity has
        Vertex AI access.
        """
        keys = provider_api_keys()
        keys.update(await self.credential_repository.list_api_keys())
        return keys

    async def _enabled_keys(self) -> set[tuple[str, str]]:
        rows = await self.repository.list_all()
        return {(r.provider, r.model_id) for r in rows if r.is_enabled}

    async def _effective_catalog(self) -> list[SupportedModel]:
        curated = await get_whitelist()
        discovered = [
            _catalog_entry(row) for row in await self.catalog_repository.list_all()
        ]
        return [*curated, *discovered]

    async def _provider_connection(
        self, provider: str
    ) -> tuple[str | None, str | None]:
        if provider == ModelProviderType.ollama.value:
            return None, await self.credential_repository.get_base_url(provider)
        return (await self._provider_api_keys()).get(provider), None

    async def list_available(self) -> list[SupportedModel]:
        """The models users may pick: whitelist ∧ provider key ∧ admin-enabled."""
        catalog = await self._effective_catalog()
        keys = await self._provider_api_keys()
        base_urls = await self.credential_repository.list_base_urls()
        enabled = await self._enabled_keys()
        return [
            m
            for m in catalog
            if m.is_available
            and m.supports_tools
            and (m.provider in keys or m.provider in base_urls)
            and (m.provider, m.model_id) in enabled
        ]

    async def supports_attachments(
        self, model_id: str | None, *, documents: bool = False
    ) -> bool:
        """Whether this model accepts this attachment kind on our serving path."""
        if model_id is None:
            return False
        return any(
            model.model_id == model_id
            and model.multimodal
            and (
                not documents
                or model.provider
                in {
                    ModelProviderType.openai.value,
                    ModelProviderType.anthropic.value,
                    ModelProviderType.google.value,
                }
            )
            for model in await self._effective_catalog()
        )

    async def ensure_available(
        self, model_id: str | None, reasoning_effort: str | None = None
    ) -> ResolvedModel:
        """The chokepoint: raise ModelUnavailableError with the precise reason,
        or return what ChatModelFactory needs. Called by RunService.create
        (the pre-stream gate), Agent.build (the backstop) and TriggerService.

        `reasoning_effort` (a thread/trigger's stored choice) is clamped, not
        rejected: a level the whitelist no longer declares is discarded so a
        catalog edit can never strand an existing thread. With no (surviving)
        choice, the whitelist entry's `reasoning_effort_default` applies —
        the CDN file is the policy knob for what unset means — and a model
        with no default falls through to its provider-default path. Strict
        validation of *new* choices happens at selection time via
        `validate_reasoning_effort`."""
        if not model_id:
            raise ModelUnavailableError("", "no model is set")
        catalog = await self._effective_catalog()
        entry = next((m for m in catalog if m.model_id == model_id), None)
        if entry is None:
            raise ModelUnavailableError(
                model_id, "it is not in the supported model catalog"
            )
        if not entry.is_available:
            raise ModelUnavailableError(
                model_id, "it is no longer available from its provider"
            )
        if not entry.supports_tools:
            raise ModelUnavailableError(
                model_id, "it does not advertise the tool support Auxilia requires"
            )
        api_key, base_url = await self._provider_connection(entry.provider)
        if not api_key and not base_url:
            raise ModelUnavailableError(
                model_id,
                f"provider '{entry.provider}' is not configured",
            )
        row = await self.repository.get_by_provider_and_model_id(
            entry.provider, entry.model_id
        )
        if row is None or not row.is_enabled:
            raise ModelUnavailableError(
                model_id, "it has been disabled by a workspace admin"
            )
        # `is not None` (not truthiness): an empty string must clamp like any
        # other undeclared value, never slip through to the factory.
        if (
            reasoning_effort is not None
            and reasoning_effort not in entry.reasoning_effort_levels
        ):
            logger.warning(
                "Stored reasoning_effort %r is not declared for model %s; "
                "falling back to the model's default",
                reasoning_effort,
                model_id,
            )
            reasoning_effort = None
        if reasoning_effort is None:
            reasoning_effort = entry.reasoning_effort_default
        return ResolvedModel(
            provider=entry.provider,
            model_id=entry.model_id,
            runtime_model_id=entry.runtime_model_id or entry.model_id,
            api_key=api_key,
            base_url=base_url,
            reasoning_effort=reasoning_effort,
            minimal_reasoning_effort=(
                entry.reasoning_effort_levels[0]
                if entry.reasoning_effort_levels
                else None
            ),
            supports_web_search=bool(entry.supports_web_search),
            supports_tool_search=entry.supports_tool_search,
            context_window=entry.context_window,
        )

    @staticmethod
    async def _declared_effort_levels(model_id: str | None) -> list[str]:
        whitelist = await get_whitelist()
        entry = next((m for m in whitelist if m.model_id == model_id), None)
        return list(entry.reasoning_effort_levels) if entry else []

    @staticmethod
    async def is_reasoning_effort_declared(
        model_id: str | None, reasoning_effort: str
    ) -> bool:
        """Whether the whitelist declares this level for the model — for
        callers that clamp a *stored* value instead of rejecting it (e.g.
        re-pointing a trigger's model with a stale carried-over effort)."""
        return reasoning_effort in await ModelService._declared_effort_levels(model_id)

    @staticmethod
    async def validate_reasoning_effort(
        model_id: str | None, reasoning_effort: str | None
    ) -> None:
        """Strict gate for user-supplied effort choices (thread and trigger
        creation): the value must be one of the model's declared levels.
        None always passes — it means "the model's default"."""
        if reasoning_effort is None:
            return
        levels = await ModelService._declared_effort_levels(model_id)
        if reasoning_effort not in levels:
            raise DomainValidationError(
                f"Model '{model_id}' does not support reasoning effort "
                f"'{reasoning_effort}'"
                + (f" (supported: {', '.join(levels)})" if levels else "")
            )

    @staticmethod
    async def list_whitelisted() -> list[SupportedModel]:
        """The full whitelist, ignoring availability — for labeling models
        that are disabled or keyless (e.g. a trigger pinned to a model an
        admin turned off). Models that left the whitelist entirely appear
        nowhere; callers fall back to the raw id."""
        return await get_whitelist()

    async def list_catalog(self) -> list[SupportedModel]:
        """Curated models plus this workspace's discovered provider models."""
        return await self._effective_catalog()

    async def is_available(self, model_id: str | None) -> bool:
        try:
            await self.ensure_available(model_id)
        except ModelUnavailableError:
            return False
        return True

    async def list_manage(self) -> list[ManagedModelResponse]:
        """Every whitelist model with its enablement state, plus orphan rows.

        Providers without credentials are included so Settings can always show
        the complete catalog and let an admin configure them.
        """
        catalog = await self._effective_catalog()
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
                prices=m.prices,
                supports_tools=m.supports_tools,
                is_available=m.is_available,
                is_enabled=(row := rows.get((m.provider, m.model_id))) is not None
                and row.is_enabled,
                is_default=row is not None and row.is_default,
                is_quick=row is not None and row.is_quick,
                deprecated=not m.is_available,
            )
            for m in catalog
        ]
        catalog_keys = {(m.provider, m.model_id) for m in catalog}
        managed.extend(
            _managed(None, row)
            for key, row in sorted(rows.items())
            if key not in catalog_keys
        )
        return managed

    async def set_enabled(
        self, provider: str, model_id: str, is_enabled: bool
    ) -> ManagedModelResponse:
        catalog = await self._effective_catalog()
        entry = next(
            (m for m in catalog if m.provider == provider and m.model_id == model_id),
            None,
        )
        if entry is None:
            # Orphan rows (model left the whitelist) may still be toggled off,
            # never on — re-enabling something unservable makes no sense.
            row = await self.repository.get_by_provider_and_model_id(provider, model_id)
            if row is None or is_enabled:
                raise NotFoundError("Model not found in the supported catalog")
        if is_enabled:
            if entry is not None and not entry.is_available:
                raise DomainValidationError(
                    "Refresh Ollama before enabling a model that is no longer present."
                )
            if entry is not None and not entry.supports_tools:
                raise DomainValidationError(
                    "This model does not advertise tool support, which Auxilia requires."
                )
            api_key, base_url = await self._provider_connection(provider)
            if not api_key and not base_url:
                raise DomainValidationError(
                    f"Configure provider '{provider}' before enabling models."
                )
        if not is_enabled:
            available = await self.list_available()
            target_is_available = any(
                m.provider == provider and m.model_id == model_id for m in available
            )
            remaining = [
                m
                for m in available
                if not (m.provider == provider and m.model_id == model_id)
            ]
            if target_is_available and not remaining:
                raise DomainValidationError(
                    "Cannot disable the last available model in the workspace."
                )

        # Locked so a concurrent set_default can't re-flag the row between
        # this read and the auto-unset below.
        row = await self.repository.get_by_provider_and_model_id(
            provider, model_id, for_update=True
        )
        if row is None:
            if self.workspace_id is None:
                raise RuntimeError("workspace_id is required to configure models")
            row = await self.repository.create(
                ModelCreateDB(
                    workspace_id=self.workspace_id,
                    provider=provider,
                    model_id=model_id,
                    is_enabled=is_enabled,
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
            if not is_enabled and row.is_quick:
                row.is_quick = False
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
        return await self._set_role(provider, model_id, "is_default")

    async def set_quick(self, provider: str, model_id: str) -> ManagedModelResponse:
        """Flag one model as the workspace quick model — the one the runtime
        uses for its short intermediate calls (lazy tool-discovery routing).
        Same availability contract as `set_default`."""
        return await self._set_role(provider, model_id, "is_quick")

    async def _set_role(
        self, provider: str, model_id: str, flag: Literal["is_default", "is_quick"]
    ) -> ManagedModelResponse:
        resolved = await self.ensure_available(model_id)
        if resolved.provider != provider:
            raise NotFoundError("Model not found in the supported catalog")

        # Lock the target row and revalidate under the lock: concurrent admin
        # mutations could otherwise persist a disabled model in the role
        # (racing set_enabled) or trip the single-row unique index with a
        # raw 500 (racing another set).
        row = await self.repository.get_by_provider_and_model_id(
            provider, model_id, for_update=True
        )
        if row is None or not row.is_enabled:
            raise ModelUnavailableError(
                model_id, "it has been disabled by a workspace admin"
            )

        current = await self._role_row(flag, for_update=True)
        if current and (current.provider, current.model_id) != (provider, model_id):
            setattr(current, flag, False)
            self.db.add(current)
            # Flush the unset before the set so the partial unique index never
            # sees two flagged rows.
            await self.db.flush()

        if not getattr(row, flag):
            setattr(row, flag, True)
            self.db.add(row)
            await self.db.flush()
            await self.db.refresh(row)

        catalog = await self._effective_catalog()
        entry = next(
            (m for m in catalog if m.provider == provider and m.model_id == model_id),
            None,
        )
        return _managed(entry, row)

    async def _role_row(
        self, flag: Literal["is_default", "is_quick"], *, for_update: bool = False
    ) -> ModelDB | None:
        if flag == "is_default":
            return await self.repository.get_default(for_update=for_update)
        return await self.repository.get_quick(for_update=for_update)

    async def clear_default(self) -> None:
        """Back to automatic: consumers fall back to the first available model."""
        await self._clear_role("is_default")

    async def clear_quick(self) -> None:
        """Unset the quick model: the runtime falls back to the thread's model
        at its lowest reasoning effort."""
        await self._clear_role("is_quick")

    async def _clear_role(self, flag: Literal["is_default", "is_quick"]) -> None:
        row = await self._role_row(flag, for_update=True)
        if row is not None:
            setattr(row, flag, False)
            self.db.add(row)
            await self.db.flush()

    async def _unset_roles_where(self, predicate: Callable[[ModelDB], bool]) -> None:
        """Drop the default/quick flags from rows `predicate` rejects — the
        admin mutations that can make a flagged model unservable (provider
        key removed, Ollama model gone) call this so a role never points at
        a model the runtime cannot build."""
        flags: tuple[Literal["is_default", "is_quick"], ...] = (
            "is_default",
            "is_quick",
        )
        for flag in flags:
            row = await self._role_row(flag, for_update=True)
            if row is not None and predicate(row):
                setattr(row, flag, False)
                self.db.add(row)
                await self.db.flush()

    async def resolve_quick(self) -> ResolvedModel | None:
        """The quick model, resolved for `ChatModelFactory`, or None when
        unset or no longer available — callers fall back, never fail, since
        the quick model is an optimisation and not a dependency."""
        row = await self.repository.get_quick()
        if row is None:
            return None
        try:
            return await self.ensure_available(row.model_id)
        except ModelUnavailableError:
            logger.warning(
                "Quick model %s is flagged but unavailable; falling back",
                row.model_id,
            )
            return None

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
    def _provider_type(provider: str) -> ModelProviderType:
        try:
            return ModelProviderType(provider)
        except ValueError as exc:
            raise NotFoundError("Model provider not found") from exc

    async def list_provider_configs(self) -> list[ModelProviderConfigResponse]:
        stored = await self.credential_repository.list_api_keys()
        fallback = provider_api_keys()
        base_urls = await self.credential_repository.list_base_urls()
        configs: list[ModelProviderConfigResponse] = []
        for provider_type in ModelProviderType:
            provider = provider_type.value
            if provider_type is ModelProviderType.ollama:
                base_url = base_urls.get(provider)
                configs.append(
                    ModelProviderConfigResponse(
                        name=provider_type,
                        is_configured=bool(base_url),
                        source=(
                            ProviderCredentialSource.database
                            if base_url
                            else ProviderCredentialSource.none
                        ),
                        configuration_type=ProviderConfigurationType.base_url,
                        base_url=base_url,
                    )
                )
                continue
            key = stored.get(provider) or fallback.get(provider)
            if provider in stored:
                source = ProviderCredentialSource.database
            elif key == GOOGLE_ADC_SENTINEL:
                source = ProviderCredentialSource.adc
            elif key:
                source = ProviderCredentialSource.environment
            else:
                source = ProviderCredentialSource.none
            configs.append(
                ModelProviderConfigResponse(
                    name=provider_type,
                    is_configured=bool(key),
                    source=source,
                    last4=key[-4:]
                    if key and len(key) >= 10 and source != ProviderCredentialSource.adc
                    else None,
                    key_length=(
                        len(key)
                        if key and source != ProviderCredentialSource.adc
                        else None
                    ),
                )
            )
        return configs

    async def set_provider_api_key(
        self, provider: str, api_key: str
    ) -> ModelProviderConfigResponse:
        provider_type = self._provider_type(provider)
        if provider_type is ModelProviderType.ollama:
            raise DomainValidationError("Ollama is configured with a base URL")
        api_key = api_key.strip()
        if not api_key:
            raise DomainValidationError("API key cannot be empty")
        if provider_type is ModelProviderType.google and api_key == GOOGLE_ADC_SENTINEL:
            raise DomainValidationError("'adc' is reserved for Google ADC discovery")
        await self.credential_repository.set_api_key(provider_type.value, api_key)
        return ModelProviderConfigResponse(
            name=provider_type,
            is_configured=True,
            source=ProviderCredentialSource.database,
            last4=api_key[-4:] if len(api_key) >= 10 else None,
            key_length=len(api_key),
        )

    async def delete_provider_api_key(
        self, provider: str
    ) -> ModelProviderConfigResponse:
        provider_type = self._provider_type(provider)
        if provider_type is ModelProviderType.ollama:
            raise DomainValidationError("Ollama is configured with a base URL")
        await self.credential_repository.delete_api_key(provider_type.value)
        configs = await self.list_provider_configs()
        config = next(config for config in configs if config.name == provider_type)
        if not config.is_configured:
            await self._unset_roles_where(
                lambda row: row.provider == provider_type.value
            )
        return config

    async def connect_ollama(self, base_url: str) -> OllamaDiscoveryResponse:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to configure Ollama")
        normalized = await validate_ollama_url(base_url)
        discovered = await discover_ollama_models(normalized)
        await self.credential_repository.set_base_url(
            ModelProviderType.ollama.value, normalized
        )
        return await self._persist_ollama_discovery(normalized, discovered)

    async def refresh_ollama(self) -> OllamaDiscoveryResponse:
        base_url = await self.credential_repository.get_base_url(
            ModelProviderType.ollama.value
        )
        if not base_url:
            raise DomainValidationError("Configure the Ollama base URL first")
        discovered = await discover_ollama_models(base_url)
        return await self._persist_ollama_discovery(base_url, discovered)

    async def _persist_ollama_discovery(
        self, base_url: str, discovered: list[DiscoveredOllamaModel]
    ) -> OllamaDiscoveryResponse:
        provider = ModelProviderType.ollama.value
        await self.catalog_repository.mark_all_unavailable(provider)
        for model in discovered:
            await self.catalog_repository.upsert(
                provider=provider,
                **model.model_dump(),
            )
        usable_model_ids = {
            model.model_id for model in discovered if model.supports_tools
        }
        await self._unset_roles_where(
            lambda row: (
                row.provider == provider and row.model_id not in usable_model_ids
            )
        )
        config = ModelProviderConfigResponse(
            name=ModelProviderType.ollama,
            is_configured=True,
            source=ProviderCredentialSource.database,
            configuration_type=ProviderConfigurationType.base_url,
            base_url=base_url,
        )
        return OllamaDiscoveryResponse(
            config=config,
            discovered_count=len(discovered),
            available_count=sum(model.supports_tools for model in discovered),
        )

    async def disconnect_ollama(self) -> ModelProviderConfigResponse:
        provider = ModelProviderType.ollama.value
        await self.credential_repository.delete_provider_config(provider)
        await self.catalog_repository.delete_by_provider(provider)
        await self.repository.delete_by_provider(provider)
        return ModelProviderConfigResponse(
            name=ModelProviderType.ollama,
            is_configured=False,
            source=ProviderCredentialSource.none,
            configuration_type=ProviderConfigurationType.base_url,
        )

    @staticmethod
    async def sync() -> WhitelistSyncResponse:
        return WhitelistSyncResponse(**await sync_whitelist())


def get_model_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> ModelService:
    return ModelService(db, workspace_id)
