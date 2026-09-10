"""Thread-level read authorization, shared by the thread and protocol routers.

Two audiences can open a thread: its owner, and an admin of its agent
(workspace admin, or agent owner/admin), who gets a read-only view. The thread
router resolved that for `GET /threads/{id}`; the protocol endpoints the chat
page hydrates from (`/state`, `/history`, `/messages/{id}`, `/stream/events`)
must accept the same audience, or an admin sees the header and an empty
conversation. Commands stay owner-only (`authorize_thread` in
`app/agents/runs/router.py`).
"""

from fastapi import Depends

from app.agents.core.service import AgentService, get_agent_service
from app.agents.models import EffectivePermission
from app.auth.dependencies import get_current_user
from app.threads.schemas import ThreadResponse, ViewerRole
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


async def resolve_viewer_role(
    thread: ThreadResponse,
    current_user: UserDB,
    agent_service: AgentService,
) -> ViewerRole | None:
    """Return the viewer's role on this thread, or raise 403.

    - Owner of the thread → ``None`` (full access).
    - Workspace admin or per-agent owner/admin → ``"admin"`` (read-only).
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
    )
    return "admin"


async def authorize_thread_read(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> ThreadResponse:
    """Load the thread for a read: its owner, or an admin of its agent
    (404 if missing, 403 otherwise)."""
    thread = await service.get(thread_id)
    await resolve_viewer_role(thread, current_user, agent_service)
    return thread
