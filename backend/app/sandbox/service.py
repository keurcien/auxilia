from uuid import UUID

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError
from app.sandbox.models import SandboxDB, SandboxProviderType
from app.sandbox.repository import SandboxRepository
from app.sandbox.schemas import (
    SandboxAgentResponse,
    SandboxCreate,
    SandboxCreateDB,
    SandboxPatch,
    SandboxResponse,
    SandboxSecretHint,
    config_extras,
    validate_config,
)
from app.service import BaseService
from app.utils.encryption import decrypt_value, encrypt_value


class SandboxService(BaseService[SandboxDB, SandboxRepository]):
    not_found_message = "Sandbox not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, SandboxRepository(db))

    @staticmethod
    def _validate(
        provider: SandboxProviderType, url: str, secret: str | None, config: dict
    ):
        try:
            return validate_config(provider, url=url, secret=secret, config=config)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(loc) for loc in first["loc"] if loc != "provider")
            detail = f"{field}: {first['msg']}" if field else first["msg"]
            raise DomainValidationError(f"Invalid sandbox config — {detail}") from exc

    @staticmethod
    def to_response(row: SandboxDB) -> SandboxResponse:
        return SandboxResponse(
            **row.model_dump(exclude={"encrypted_secret"}),
            has_secret=row.encrypted_secret is not None,
        )

    async def create(self, data: SandboxCreate) -> SandboxResponse:
        validated = self._validate(data.provider, data.url, data.secret, data.config)
        row = await self.repository.create(
            SandboxCreateDB(
                name=data.name,
                description=data.description,
                provider=data.provider,
                url=data.url,
                config=config_extras(validated),
                encrypted_secret=(encrypt_value(data.secret) if data.secret else None),
            )
        )
        return self.to_response(row)

    async def list_responses(self) -> list[SandboxResponse]:
        return [self.to_response(row) for row in await self.repository.list()]

    async def get_response(self, sandbox_id: UUID) -> SandboxResponse:
        return self.to_response(await self.get_or_404(sandbox_id))

    async def update(self, sandbox_id: UUID, data: SandboxPatch) -> SandboxResponse:
        row = await self.get_or_404(sandbox_id)

        # Re-validate the merged result before mutating anything, so a patch
        # can never leave an invalid config behind. An omitted/empty secret
        # keeps the stored one (write-only field).
        url = data.url if data.url is not None else row.url
        config = data.config if data.config is not None else row.config
        secret = data.secret or (
            decrypt_value(row.encrypted_secret) if row.encrypted_secret else None
        )
        validated = self._validate(row.provider, url, secret, config)

        updated = await self.repository.update(row, data)
        updated.config = config_extras(validated)
        if data.secret:
            updated.encrypted_secret = encrypt_value(data.secret)
        self.db.add(updated)
        await self.db.flush()
        await self.db.refresh(updated)
        return self.to_response(updated)

    async def list_agents(self, sandbox_id: UUID) -> list[SandboxAgentResponse]:
        """Agents currently bound to the sandbox (delete-guard dialog)."""
        await self.get_or_404(sandbox_id)
        # Function-level import: agents.sandboxes imports sandbox models, so
        # resolving it lazily keeps the modules cycle-free.
        from app.agents.sandboxes.repository import AgentSandboxRepository

        agents = await AgentSandboxRepository(self.db).list_agents_for_sandbox(
            sandbox_id
        )
        return [
            SandboxAgentResponse(
                id=agent.id, name=agent.name, emoji=agent.emoji, color=agent.color
            )
            for agent in agents
        ]

    async def delete(self, sandbox_id: UUID, *, detach_agents: bool = False) -> None:
        """Refused while agents are bound (consistent with MCP bindings)
        unless `detach_agents` — the dialog's explicit confirm — removes the
        bindings first. Threads are never bound to a sandbox, so detached
        agents simply run without code execution afterwards."""
        row = await self.get_or_404(sandbox_id)
        from app.agents.sandboxes.repository import AgentSandboxRepository

        bindings = AgentSandboxRepository(self.db)
        if detach_agents:
            await bindings.delete_all_for_sandbox(sandbox_id)
        elif agents := await bindings.list_agents_for_sandbox(sandbox_id):
            raise DomainValidationError(
                f"Sandbox is used by {len(agents)} agent(s) — detach it first"
            )
        await self.repository.delete(row)

    async def get_secret_hint(self, sandbox_id: UUID) -> SandboxSecretHint:
        row = await self.get_or_404(sandbox_id)
        if not row.encrypted_secret:
            return SandboxSecretHint(is_set=False)
        secret = decrypt_value(row.encrypted_secret)
        # Only reveal the last 4 for secrets long enough that it stays a small
        # fraction of the value; short secrets return length only.
        last4 = secret[-4:] if len(secret) >= 10 else None
        return SandboxSecretHint(is_set=True, last4=last4, length=len(secret))


def get_sandbox_service(db: AsyncSession = Depends(get_db)) -> SandboxService:
    return SandboxService(db)
