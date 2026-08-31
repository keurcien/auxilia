"""Route-level agent permission gates.

The sibling of `app/auth/dependencies.py`: that one gates on the *workspace*
role, this one on the caller's resolved permission for the agent named in the
path. Both are factories, so a route reads as a declaration
(`Depends(require_agent_permission(EffectivePermission.editor,
action="edit this agent's MCP servers"))`) instead of a check buried in the
handler body. `action` is required: it completes the sentence the caller reads
back as "Not authorized to …".

Endpoints whose service already gates (the `AgentService` mutations) do not
use this — they call `AgentService.require_permission` themselves, because
Slack and the trigger scanner reach those methods without an HTTP request.
Both paths end in the same chokepoint.
"""

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.models import EffectivePermission
from app.auth.dependencies import get_current_user
from app.users.models import UserDB


def require_agent_permission(
    at_least: EffectivePermission,
    *,
    action: str,
    include_archived: bool = False,
) -> Callable:
    """A dependency requiring `at_least` on the `agent_id` in the path.

    Raises 404 for an agent the caller cannot see and 403 when their
    permission is too weak — `action` completes "Not authorized to …".
    """

    async def dependency(
        agent_id: UUID,
        current_user: UserDB = Depends(get_current_user),
        service: AgentService = Depends(get_agent_service),
    ) -> EffectivePermission:
        return await service.require_permission(
            agent_id,
            at_least=at_least,
            action=action,
            user_id=current_user.id,
            user_role=current_user.role,
            user_team_id=current_user.team_id,
            include_archived=include_archived,
        )

    return dependency
