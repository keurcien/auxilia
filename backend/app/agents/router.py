from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.dependencies import require_agent_permission
from app.agents.mcp_servers.service import (
    AgentMCPServerService,
    get_agent_mcp_server_service,
)
from app.agents.models import EffectivePermission
from app.agents.schemas import (
    AgentConfig,
    AgentListResponse,
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
from app.pagination import Page, PageParams
from app.threads.schemas import AgentThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/", response_model=AgentResponse, status_code=201)
async def create_agent(
    config: AgentConfig,
    current_user: UserDB = Depends(require_editor),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    """Create an agent from a full config document (scalars + MCP bindings +
    subagents) atomically — the create counterpart of PUT /{agent_id}/config."""
    return await service.create_from_config(
        config,
        owner_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
    )


# The list endpoint serializes through the slim schema: response_model
# filtering drops `instructions` and the bindings' tool maps, which cuts the
# payload by ~80% on real workspaces. Detail (GET /{agent_id}) stays full.
@router.get("/", response_model=list[AgentListResponse])
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


@router.put("/{agent_id}/config", response_model=AgentResponse)
async def set_agent_config(
    agent_id: UUID,
    config: AgentConfig,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    """Atomic whole-config save: scalars + MCP bindings + subagents."""
    return await service.set_config(
        agent_id,
        config,
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


@router.get(
    "/{agent_id}/permissions",
    response_model=list[AgentPermissionResponse],
    dependencies=[
        Depends(
            require_agent_permission(
                EffectivePermission.admin, action="view this agent's permissions"
            )
        )
    ],
)
async def get_agent_permissions(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionResponse]:
    return await service.get_permissions(agent_id)


@router.put(
    "/{agent_id}/permissions",
    response_model=list[AgentPermissionResponse],
    dependencies=[
        Depends(
            require_agent_permission(
                EffectivePermission.admin, action="manage this agent's permissions"
            )
        )
    ],
)
async def set_agent_permissions(
    agent_id: UUID,
    permissions: list[AgentPermissionCreate],
    service: AgentService = Depends(get_agent_service),
) -> list[AgentPermissionResponse]:
    return await service.set_permissions(agent_id, permissions)


# Team grants confer Member access, so binding a team is an edit of the agent —
# reading and writing the bindings both sit at editor.
_require_team_manager = require_agent_permission(
    EffectivePermission.editor, action="manage this agent's teams"
)


@router.get(
    "/{agent_id}/teams",
    response_model=AgentTeamsResponse,
    dependencies=[Depends(_require_team_manager)],
)
async def get_agent_teams(
    agent_id: UUID,
    service: AgentService = Depends(get_agent_service),
) -> AgentTeamsResponse:
    return AgentTeamsResponse(team_ids=await service.get_team_ids(agent_id))


@router.put(
    "/{agent_id}/teams",
    response_model=AgentTeamsResponse,
    dependencies=[Depends(_require_team_manager)],
)
async def set_agent_teams(
    agent_id: UUID,
    data: AgentTeamsSet,
    service: AgentService = Depends(get_agent_service),
) -> AgentTeamsResponse:
    return AgentTeamsResponse(team_ids=await service.set_teams(agent_id, data.team_ids))


# Binding an MCP server, retyping its tool map or syncing it are all edits of
# the agent's configuration; they were login-only until now (design review §4.4).
_require_binding_editor = require_agent_permission(
    EffectivePermission.editor, action="edit this agent's MCP servers"
)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}",
    response_model=AgentMCPServerResponse,
    status_code=201,
    dependencies=[Depends(_require_binding_editor)],
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
    "/{agent_id}/mcp-servers/{server_id}",
    response_model=AgentMCPServerResponse,
    dependencies=[Depends(_require_binding_editor)],
)
async def update_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    data: AgentMCPServerPatch,
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> AgentMCPServerResponse:
    return await service.update(agent_id, server_id, data)


@router.delete(
    "/{agent_id}/mcp-servers/{server_id}",
    status_code=204,
    dependencies=[Depends(_require_binding_editor)],
)
async def delete_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    service: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> None:
    await service.delete(agent_id, server_id)


@router.post(
    "/{agent_id}/mcp-servers/{server_id}/sync-tools",
    response_model=AgentMCPServerResponse,
    dependencies=[Depends(_require_binding_editor)],
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


@router.get(
    "/{agent_id}/is-ready",
    dependencies=[
        Depends(
            require_agent_permission(
                EffectivePermission.member, action="use this agent"
            )
        )
    ],
)
async def is_ready(
    agent_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    return await service.describe_readiness(agent_id, str(current_user.id))


@router.get(
    "/{agent_id}/threads",
    response_model=Page[AgentThreadResponse],
    dependencies=[
        Depends(
            require_agent_permission(
                EffectivePermission.admin, action="view this agent's threads"
            )
        )
    ],
)
async def list_agent_threads(
    agent_id: UUID,
    page: PageParams = Depends(),
    thread_service: ThreadService = Depends(get_thread_service),
) -> Page[AgentThreadResponse]:
    """List an agent's threads across users, newest first. Restricted to agent
    owners and admins (workspace or agent-level)."""
    return await thread_service.list_for_agent(agent_id, page)
