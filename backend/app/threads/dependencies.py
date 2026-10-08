"""Thread-level read authorization, shared by the thread and protocol routers.

Two audiences can open a thread: its owner, and an admin of its agent (agent
owner or agent-level admin grant), who gets a read-only view. The workspace
admin role alone does not grant it: conversations stay private to the agent's
own admins. The thread
router resolved that for `GET /threads/{id}`; the protocol endpoints the chat
page hydrates from (`/state`, `/history`, `/messages/{id}`, `/stream/events`)
must accept the same audience, or an admin sees the header and an empty
conversation. Commands stay owner-only (`authorize_thread` in
`app/runtime/api/runs_router.py`).
"""

from fastapi import Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.models import EffectivePermission
from app.auth.dependencies import get_current_user
from app.threads.models import ThreadDB
from app.threads.schemas import ViewerRole
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


async def resolve_viewer_role(
    thread: ThreadDB,
    current_user: UserDB,
    agent_service: AgentService,
) -> ViewerRole | None:
    """Return the viewer's role on this thread, or raise 403.

    - Owner of the thread → ``None`` (full access).
    - Agent owner or agent-level admin → ``"admin"`` (read-only). A workspace
      admin with no such grant on the agent is denied like anyone else.
    - Anyone else → ``PermissionDeniedError``.
    """
    if thread.user_id == current_user.id:
        return None
    await agent_service.require_permission(
        thread.agent_id,
        at_least=EffectivePermission.admin,
        action="view this thread",
        user_id=current_user.id,
        user_role=current_user.role,
        workspace_admin_bypass=False,
    )
    return "admin"


async def authorize_thread_read(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> ThreadDB:
    """Load the thread for a read: its owner, or an agent-level admin of its
    agent (404 if missing, 403 otherwise)."""
    thread = await service.get(thread_id)
    await resolve_viewer_role(thread, current_user, agent_service)
    return thread
