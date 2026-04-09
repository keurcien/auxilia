from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.mcp_servers.service import (
    AgentMCPServerService,
    get_agent_mcp_server_service,
)
from app.agents.models import (
    AgentCreate,
    AgentMCPServerCreate,
    AgentMCPServerRead,
    AgentMCPServerUpdate,
    AgentPermissionRead,
    AgentPermissionWrite,
    AgentRead,
    AgentSubagentRead,
    AgentUpdate,
)
from app.agents.subagents.service import SubagentService, get_subagent_service
from app.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
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
    return await service.list_agents(
        user_id=current_user.id, user_role=current_user.role
    )


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
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentRead:
    return await service.update_agent(
        agent_id, agent_update, user_id=current_user.id, user_role=current_user.role
    )


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
    response_model=AgentMCPServerRead,
    status_code=201,
)
async def create_or_update_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    data: AgentMCPServerCreate,
    current_user: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerRead:
    return await service.create_or_update(
        agent_id, server_id, data, str(current_user.id)
    )


@router.patch(
    "/{agent_id}/mcp-servers/{server_id}", response_model=AgentMCPServerRead
)
async def update_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    data: AgentMCPServerUpdate,
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerRead:
    return await service.update(agent_id, server_id, data)


@router.delete("/{agent_id}/mcp-servers/{server_id}", status_code=204)
async def delete_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> None:
    await service.delete(agent_id, server_id)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}/sync-tools",
    response_model=AgentMCPServerRead,
)
async def sync_tools(
    agent_id: UUID,
    server_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerRead:
    return await service.sync_tools(agent_id, server_id, str(current_user.id))


@router.post(
    "/{agent_id}/subagents/{subagent_id}",
    response_model=AgentSubagentRead,
    status_code=201,
)
async def create_subagent(
    agent_id: UUID,
    subagent_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SubagentService = Depends(get_subagent_service),
) -> AgentSubagentRead:
    return await service.create(agent_id, subagent_id)


@router.delete("/{agent_id}/subagents/{subagent_id}", status_code=204)
async def delete_subagent(
    agent_id: UUID,
    subagent_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SubagentService = Depends(get_subagent_service),
) -> None:
    await service.delete(agent_id, subagent_id)


@router.get("/{agent_id}/is-ready")
async def is_ready(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    return await service.check_ready(agent_id, str(current_user.id))
