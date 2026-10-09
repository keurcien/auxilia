"""Thread-level read authorization, shared by the thread and protocol routers.

Three audiences can open a thread: its owner, an admin of its agent, and for a
trigger-created thread anyone who can view that trigger. The latter two get a
read-only view. Commands stay owner-only (`authorize_thread` in
`app/runtime/api/runs_router.py`).
"""

from fastapi import Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.models import EffectivePermission
from app.auth.dependencies import get_current_user
from app.threads.models import ThreadDB
from app.threads.schemas import ViewerRole
from app.threads.service import ThreadService, get_thread_service
from app.triggers.repository import TriggerRepository
from app.users.models import UserDB
from app.visibility import ResourceVisibility, is_resource_visible


async def resolve_viewer_role(
    thread: ThreadDB,
    current_user: UserDB,
    agent_service: AgentService,
) -> ViewerRole | None:
    """Return the viewer's role on this thread, or raise 403.

    - Owner of the thread → ``None`` (full access).
    - Viewer of the trigger that created it → ``"admin"`` (read-only).
    - Workspace admin or per-agent owner/admin → ``"admin"`` (read-only).
    - Anyone else → ``PermissionDeniedError``.
    """
    if thread.user_id == current_user.id:
        return None
    if thread.trigger_id is not None:
        triggers = TriggerRepository(agent_service.db, thread.workspace_id)
        trigger = await triggers.get(thread.trigger_id)
        if trigger is not None:
            team_ids = (
                set(await triggers.list_team_ids(trigger.id))
                if trigger.visibility == ResourceVisibility.teams
                else set()
            )
            if is_resource_visible(
                visibility=trigger.visibility,
                owner_id=trigger.owner_id,
                team_ids=team_ids,
                user=current_user,
            ):
                return "admin"
    await agent_service.require_permission(
        thread.agent_id,
        at_least=EffectivePermission.admin,
        action="view this thread",
        user_id=current_user.id,
        user_role=current_user.role,
    )
    return "admin"


async def authorize_thread_read(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> ThreadDB:
    """Load the thread for a read using the audiences from resolve_viewer_role."""
    thread = await service.get(thread_id)
    await resolve_viewer_role(thread, current_user, agent_service)
    return thread
