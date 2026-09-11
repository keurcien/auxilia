import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService, get_agent_service
from app.auth.dependencies import detect_auth_method, get_current_user
from app.database import get_db
from app.exceptions import PermissionDeniedError
from app.pagination import Page, PageParams
from app.threads.dependencies import resolve_viewer_role
from app.threads.models import ThreadSource
from app.threads.schemas import ThreadCreate, ThreadPatch, ThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}")
async def read_thread(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict:
    """Thread metadata (`thread`, with its agent) and the caller's viewer role.

    The conversation is not here. The client hydrates it from the protocol
    snapshot (`GET /threads/{id}/state`), and this endpoint used to ship the
    same messages a second time — for a heavy thread, 16 MB twice per page
    load — so it no longer opens the checkpoint at all. Interrupt state comes
    from the snapshot's `next` / `tasks`.
    """
    thread = await service.get(thread_id)
    viewer_role = await resolve_viewer_role(thread, current_user, agent_service)
    thread_read = await service.get_with_agent(thread_id)
    return {"thread": thread_read, "viewer_role": viewer_role}


@router.get("/")
async def get_threads(
    page: PageParams = Depends(),
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> Page[ThreadResponse]:
    return await service.list(current_user.id, page)


@router.post("/")
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    source = (
        ThreadSource.web
        if detect_auth_method(request, current_user) == "cookie"
        else ThreadSource.api
    )
    return await service.create(thread_data, current_user.id, source)


@router.patch("/{thread_id}")
async def update_thread(
    thread_id: str,
    data: ThreadPatch,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to edit this thread")
    return await service.update(thread_id, data)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: the service's session
) -> None:
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to delete this thread")
    await service.delete(thread_id)
    # Commit the row delete BEFORE purging checkpoints — the order
    # `purge_checkpoints` documents, and the reverse of what this endpoint used
    # to do. Checkpoints live on a separate auto-committed connection and cannot
    # be rolled back, so purging first meant a failed commit left a thread whose
    # entire history was irrecoverably gone (design review §5.5). The other
    # direction fails safe: a purge that errors leaves a deleted thread's
    # checkpoints orphaned, which is invisible and reclaimable.
    await db.commit()
    # Past the commit the delete has happened, so a purge failure must not turn
    # into a 500: the client would retry and get a 404 for a thread that really
    # is gone. Orphaned checkpoints are invisible and reclaimable; a confusing
    # error on a successful operation is not. Logged loudly so they can be.
    try:
        await service.purge_checkpoints([thread_id])
    except Exception:
        logger.exception(
            "Thread %s was deleted but its checkpoints could not be purged; "
            "they are now orphaned",
            thread_id,
        )
