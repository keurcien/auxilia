from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.sharing.schemas import ScopeApplyRequest, ScopeChange, ScopePlanResponse
from app.sharing.service import SharingService, get_sharing_service
from app.users.models import UserDB


router = APIRouter(prefix="/sharing", tags=["sharing"])


@router.post("/plan", response_model=ScopePlanResponse)
async def plan_scope_change(
    request: ScopeChange,
    user: UserDB = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
) -> ScopePlanResponse:
    """List every access change a requested one implies, without applying it."""
    return await service.plan(request, user)


@router.post("/apply", status_code=204)
async def apply_scope_changes(
    request: ScopeApplyRequest,
    user: UserDB = Depends(get_current_user),
    service: SharingService = Depends(get_sharing_service),
) -> None:
    await service.apply(request.changes, user)
