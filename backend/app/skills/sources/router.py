from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.skills.schemas import (
    SkillSourceCreate,
    SkillSourcePatch,
    SkillSourcePreview,
    SkillSourceResponse,
    SkillSyncPlan,
)
from app.skills.sources.service import SkillSourceService, get_skill_source_service
from app.users.models import UserDB


# Registered before the skills router: `/skills/sources` must not be read as
# `/skills/{skill_id}`. The collection routes are declared on "" (no trailing
# slash): FastAPI's slash redirect would otherwise send `/skills/sources` to
# `/skills/{skill_id}` first, and the Next proxy normalises trailing slashes
# away, so the client cannot reach a `/skills/sources/` route at all.
router = APIRouter(prefix="/skills/sources", tags=["skills"])


@router.get("", response_model=list[SkillSourceResponse])
async def list_sources(
    user: UserDB = Depends(get_current_user),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.list(user)


@router.post("/preview", response_model=SkillSourcePreview)
async def preview_source(
    data: SkillSourceCreate,
    _: UserDB = Depends(require_admin),  # side-effect auth check
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.preview(data)


@router.post("", response_model=SkillSourceResponse, status_code=201)
async def create_source(
    data: SkillSourceCreate,
    user: UserDB = Depends(require_admin),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.create(data, user)


@router.get("/{source_id}", response_model=SkillSourceResponse)
async def get_source(
    source_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.get(source_id, user)


@router.patch("/{source_id}", response_model=SkillSourceResponse)
async def update_source(
    source_id: UUID,
    data: SkillSourcePatch,
    user: UserDB = Depends(require_admin),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.update(source_id, data, user)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: UUID,
    user: UserDB = Depends(require_admin),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    await service.delete(source_id, user)


@router.get("/{source_id}/plan", response_model=SkillSyncPlan)
async def plan_sync(
    source_id: UUID,
    user: UserDB = Depends(require_admin),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    """What the next sync would change. Reads the repository, writes nothing."""
    return await service.plan(source_id, user)


@router.post("/{source_id}/sync", response_model=SkillSourceResponse)
async def sync_source(
    source_id: UUID,
    user: UserDB = Depends(require_admin),
    service: SkillSourceService = Depends(get_skill_source_service),
):
    return await service.sync(source_id, user)
