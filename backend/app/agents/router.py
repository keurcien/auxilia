from uuid import UUID
from fastapi import APIRouter, Depends
from app.agents.models import (
    AgentCreate,
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingRead,
    AgentMCPServerBindingUpdate,
    AgentPermissionRead,
    AgentPermissionWrite,
    AgentRead,
    AgentUpdate,
)
from app.agents.service import AgentService, get_agent_service
from app.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_editor,
)
from app.users.models import UserDB

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/", response_model=AgentRead, status_code=201)
async def create_agent(
    agent: AgentCreate,
    _: UserDB = Depends(require_editor),
    service: AgentService = Depends(get_agent_service),
) -> AgentRead:
    return await service.create_agent(agent)


@router.get("/", response_model=list[AgentRead])
async def get_agents(
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentRead]:
    return await service.list_agents(user_id=current_user.id, user_role=current_user.role)


@router.get("/{agent_id}", response_model=AgentRead, response_model_by_alias=True)
async def get_agent(
    agent_id: UUID,
    current_user: UserDB | None = Depends(get_current_user_optional),
    service: AgentService = Depends(get_agent_service),
) -> AgentRead:
    return await service.get_agent(
        agent_id,
        user_id=current_user.id if current_user else None,
        user_role=current_user.role if current_user else None,
    )


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: UUID,
    agent_update: AgentUpdate,
    service: AgentService = Depends(get_agent_service),
) -> AgentRead:
    return await service.update_agent(agent_id, agent_update)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
) -> None:
    await service.delete_agent(agent_id)


@router.get("/{agent_id}/permissions", response_model=list[AgentPermissionRead])
async def get_agent_permissions(
    agent_id: UUID,
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionRead]:
    return await service.get_permissions(agent_id)


@router.put("/{agent_id}/permissions", response_model=list[AgentPermissionRead])
async def set_agent_permissions(
    agent_id: UUID,
    permissions: list[AgentPermissionWrite],
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionRead]:
    return await service.set_permissions(agent_id, permissions)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}",
    response_model=AgentMCPServerBindingRead,
    status_code=201,
)
async def create_or_update_binding(
    agent_id: UUID,
    server_id: UUID,
    binding: AgentMCPServerBindingCreate,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentMCPServerBindingRead:
    return await service.create_or_update_binding(
        agent_id, server_id, binding, str(current_user.id)
    )


@router.patch(
    "/{agent_id}/mcp-servers/{server_id}", response_model=AgentMCPServerBindingRead
)
async def update_binding(
    agent_id: UUID,
    server_id: UUID,
    binding_update: AgentMCPServerBindingUpdate,
    service: AgentService = Depends(get_agent_service),
) -> AgentMCPServerBindingRead:
    return await service.update_binding(agent_id, server_id, binding_update)


@router.delete("/{agent_id}/mcp-servers/{server_id}", status_code=204)
async def delete_binding(
    agent_id: UUID,
    server_id: UUID,
    service: AgentService = Depends(get_agent_service),
) -> None:
    await service.delete_binding(agent_id, server_id)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}/sync-tools",
    response_model=AgentMCPServerBindingRead,
)
async def sync_tools(
    agent_id: UUID,
    server_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentMCPServerBindingRead:
    return await service.sync_tools(agent_id, server_id, str(current_user.id))


@router.get("/{agent_id}/is-ready")
async def is_ready(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    return await service.check_ready(agent_id, str(current_user.id))
