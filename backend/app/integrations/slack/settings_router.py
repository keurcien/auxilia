from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.dependencies import require_agent_permission
from app.agents.models import EffectivePermission
from app.integrations.slack.schemas import AgentSlackBotResponse, AgentSlackBotUpdate
from app.integrations.slack.service import (
    AgentSlackBotService,
    get_agent_slack_bot_service,
)


router = APIRouter(prefix="/agents", tags=["agent-slack"])

_require_viewer = require_agent_permission(
    EffectivePermission.member, action="view this agent's Slack bot"
)
_require_admin = require_agent_permission(
    EffectivePermission.admin, action="configure this agent's Slack bot"
)


@router.get(
    "/{agent_id}/integrations/slack",
    response_model=AgentSlackBotResponse,
    dependencies=[Depends(_require_viewer)],
)
async def get_agent_slack_bot(
    agent_id: UUID,
    service: AgentSlackBotService = Depends(get_agent_slack_bot_service),
) -> AgentSlackBotResponse:
    return await service.get_response(agent_id)


@router.put(
    "/{agent_id}/integrations/slack",
    response_model=AgentSlackBotResponse,
    dependencies=[Depends(_require_admin)],
)
async def update_agent_slack_bot(
    agent_id: UUID,
    data: AgentSlackBotUpdate,
    service: AgentSlackBotService = Depends(get_agent_slack_bot_service),
) -> AgentSlackBotResponse:
    return await service.update(agent_id, data)


@router.delete(
    "/{agent_id}/integrations/slack",
    response_model=AgentSlackBotResponse,
    dependencies=[Depends(_require_admin)],
)
async def delete_agent_slack_bot(
    agent_id: UUID,
    service: AgentSlackBotService = Depends(get_agent_slack_bot_service),
) -> AgentSlackBotResponse:
    return await service.delete(agent_id)
