from uuid import UUID

from fastapi import APIRouter, Depends

from app.agents.dependencies import require_agent_permission
from app.agents.models import EffectivePermission
from app.auth.dependencies import get_current_user, require_admin
from app.integrations.langfuse.callback import get_langfuse_client
from app.integrations.langfuse.schemas import (
    LangfusePromptResponse,
    LangfusePromptVersion,
    LangfusePublishRequest,
    LangfuseStatusResponse,
)
from app.integrations.langfuse.service import (
    LangfusePromptService,
    get_langfuse_prompt_service,
)
from app.users.models import UserDB


router = APIRouter(tags=["langfuse"])

_read_gate = Depends(
    require_agent_permission(
        EffectivePermission.editor, action="manage this agent's Langfuse prompt"
    )
)


@router.get("/integrations/langfuse", response_model=LangfuseStatusResponse)
async def get_status(_: UserDB = Depends(get_current_user)) -> LangfuseStatusResponse:
    return LangfuseStatusResponse(enabled=get_langfuse_client() is not None)


@router.get(
    "/agents/{agent_id}/langfuse-prompt",
    response_model=LangfusePromptResponse,
    dependencies=[_read_gate],
)
async def get_prompt(
    agent_id: UUID,
    service: LangfusePromptService = Depends(get_langfuse_prompt_service),
) -> LangfusePromptResponse:
    return await service.get(agent_id)


@router.get(
    "/agents/{agent_id}/langfuse-prompt/versions",
    response_model=list[LangfusePromptVersion],
    dependencies=[_read_gate],
)
async def list_versions(
    agent_id: UUID,
    service: LangfusePromptService = Depends(get_langfuse_prompt_service),
) -> list[LangfusePromptVersion]:
    return await service.list_versions(agent_id)


@router.post(
    "/agents/{agent_id}/langfuse-prompt/publish",
    response_model=LangfusePromptVersion,
)
async def publish(
    agent_id: UUID,
    data: LangfusePublishRequest,
    _: UserDB = Depends(require_admin),
    service: LangfusePromptService = Depends(get_langfuse_prompt_service),
) -> LangfusePromptVersion:
    return await service.publish(agent_id, data.commit_message)


@router.post(
    "/agents/{agent_id}/langfuse-prompt/versions/{version}/promote",
    response_model=LangfusePromptVersion,
)
async def promote(
    agent_id: UUID,
    version: int,
    _: UserDB = Depends(require_admin),
    service: LangfusePromptService = Depends(get_langfuse_prompt_service),
) -> LangfusePromptVersion:
    return await service.promote(agent_id, version)
