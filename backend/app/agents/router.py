from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.mcp_servers.service import (
    AgentMCPServerService,
    get_agent_mcp_server_service,
)
from app.agents.schemas import (
    AgentCreate,
    AgentCreateDB,
    AgentMCPServerCreate,
    AgentMCPServerPatch,
    AgentMCPServerResponse,
    AgentPatch,
    AgentPermissionCreate,
    AgentPermissionResponse,
    AgentResponse,
    AgentSubagentResponse,
    AgentTeamsResponse,
    AgentTeamsSet,
)
from app.agents.subagents.service import SubagentService, get_subagent_service
from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_editor,
)
from app.exceptions import PermissionDeniedError
from app.threads.schemas import AgentThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/", response_model=AgentResponse, status_code=201)
async def create_agent(
    data: AgentCreate,
    current_user: UserDB = Depends(require_editor),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    return await service.create(
        AgentCreateDB(**data.model_dump(), owner_id=current_user.id)
    )


@router.get("/", response_model=list[AgentResponse])
async def get_agents(
    archived: bool = False,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentResponse]:
    return await service.list(
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
        archived=archived,
    )


@router.get("/{agent_id}", response_model=AgentResponse, response_model_by_alias=True)
async def get_agent(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    return await service.get(
        agent_id,
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    agent_update: AgentPatch,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    return await service.update(
        agent_id,
        agent_update,
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> None:
    await service.delete(agent_id, user_id=current_user.id, user_role=current_user.role)


@router.post("/{agent_id}/restore", response_model=AgentResponse)
async def restore_agent(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    return await service.restore(
        agent_id,
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )


@router.delete("/{agent_id}/permanent", status_code=204)
async def delete_agent_permanently(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> None:
    await service.delete_permanently(
        agent_id,
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )


@router.get("/{agent_id}/permissions", response_model=list[AgentPermissionResponse])
async def get_agent_permissions(
    agent_id: UUID,
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionResponse]:
    return await service.get_permissions(agent_id)


@router.put("/{agent_id}/permissions", response_model=list[AgentPermissionResponse])
async def set_agent_permissions(
    agent_id: UUID,
    permissions: list[AgentPermissionCreate],
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionResponse]:
    return await service.set_permissions(agent_id, permissions)


@router.get("/{agent_id}/teams", response_model=AgentTeamsResponse)
async def get_agent_teams(
    agent_id: UUID,
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentTeamsResponse:
    return AgentTeamsResponse(team_ids=await service.get_team_ids(agent_id))


@router.put("/{agent_id}/teams", response_model=AgentTeamsResponse)
async def set_agent_teams(
    agent_id: UUID,
    data: AgentTeamsSet,
    _: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentTeamsResponse:
    return AgentTeamsResponse(team_ids=await service.set_teams(agent_id, data.team_ids))


@router.post(
    "/{agent_id}/mcp-servers/{server_id}",
    response_model=AgentMCPServerResponse,
    status_code=201,
)
async def create_or_update_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    data: AgentMCPServerCreate,
    current_user: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerResponse:
    return await service.create_or_update(
        agent_id, server_id, data, str(current_user.id)
    )


@router.patch(
    "/{agent_id}/mcp-servers/{server_id}", response_model=AgentMCPServerResponse
)
async def update_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    data: AgentMCPServerPatch,
    _: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerResponse:
    return await service.update(agent_id, server_id, data)


@router.delete("/{agent_id}/mcp-servers/{server_id}", status_code=204)
async def delete_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    _: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> None:
    await service.delete(agent_id, server_id)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}/sync-tools",
    response_model=AgentMCPServerResponse,
)
async def sync_tools(
    agent_id: UUID,
    server_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerResponse:
    return await service.sync_tools(agent_id, server_id, str(current_user.id))


@router.post(
    "/{agent_id}/subagents/{subagent_id}",
    response_model=AgentSubagentResponse,
    status_code=201,
)
async def create_subagent(
    agent_id: UUID,
    subagent_id: UUID,
    _: UserDB = Depends(require_admin),
    service: SubagentService = Depends(get_subagent_service),
) -> AgentSubagentResponse:
    return await service.create_or_update(agent_id, subagent_id)


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
    return await service.describe_readiness(agent_id, str(current_user.id))


@router.get("/{agent_id}/threads", response_model=list[AgentThreadResponse])
async def list_agent_threads(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    thread_service: ThreadService = Depends(get_thread_service),
) -> list[AgentThreadResponse]:
    """List all threads for an agent across users. Restricted to agent owners
    and admins (workspace or agent-level)."""
    agent = await agent_service.get(
        agent_id,
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )
    if agent.current_user_permission not in ("owner", "admin"):
        raise PermissionDeniedError("Not authorized to view this agent's threads")
    return await thread_service.list_for_agent(agent_id)
