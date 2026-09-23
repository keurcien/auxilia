from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.core.service import AgentService, get_agent_service
from app.auth.dependencies import get_current_user, require_admin
from app.sandbox.schemas import (
    SandboxAgentResponse,
    SandboxCreate,
    SandboxPatch,
    SandboxResponse,
    SandboxSecretHint,
)
from app.sandbox.service import SandboxService, get_sandbox_service
from app.users.models import UserDB


sandboxes_router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


@sandboxes_router.get("/", response_model=list[SandboxResponse])
async def list_sandboxes(
    _: UserDB = Depends(get_current_user),
    service: SandboxService = Depends(get_sandbox_service),
) -> list[SandboxResponse]:
    return await service.list_responses()


@sandboxes_router.post("/", response_model=SandboxResponse, status_code=201)
async def create_sandbox(
    data: SandboxCreate,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
) -> SandboxResponse:
    return await service.create(data)


@sandboxes_router.get("/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(
    sandbox_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
) -> SandboxResponse:
    return await service.get_response(sandbox_id)


@sandboxes_router.get("/{sandbox_id}/agents", response_model=list[SandboxAgentResponse])
async def list_sandbox_agents(
    sandbox_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
    agents: AgentService = Depends(get_agent_service),
) -> list[SandboxAgentResponse]:
    await service.get_or_404(sandbox_id)  # 404 before the bindings are read
    return [
        SandboxAgentResponse(
            id=agent.id, name=agent.name, emoji=agent.emoji, color=agent.color
        )
        for agent in await agents.list_for_sandbox(sandbox_id)
    ]


@sandboxes_router.get("/{sandbox_id}/secret-hint", response_model=SandboxSecretHint)
async def get_sandbox_secret_hint(
    sandbox_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
) -> SandboxSecretHint:
    return await service.get_secret_hint(sandbox_id)


@sandboxes_router.patch("/{sandbox_id}", response_model=SandboxResponse)
async def update_sandbox(
    sandbox_id: UUID,
    data: SandboxPatch,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
) -> SandboxResponse:
    return await service.update(sandbox_id, data)


@sandboxes_router.delete("/{sandbox_id}", status_code=204)
async def delete_sandbox(
    sandbox_id: UUID,
    detach_agents: bool = False,
    _: UserDB = Depends(require_admin),
    service: SandboxService = Depends(get_sandbox_service),
    agents: AgentService = Depends(get_agent_service),
) -> None:
    """Two services, composed here: the agents module releases (or refuses to
    release) the bindings, then the sandbox row goes."""
    await agents.release_sandbox(sandbox_id, detach_agents=detach_agents)
    await service.delete(sandbox_id)
