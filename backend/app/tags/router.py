from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.tags.schemas import TagCreate, TagPatch, TagResponse
from app.tags.service import TagService, get_tag_service
from app.users.models import UserDB


router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/", response_model=list[TagResponse])
async def list_tags(
    _: UserDB = Depends(get_current_user),
    service: TagService = Depends(get_tag_service),
) -> list[TagResponse]:
    return await service.list()


@router.post("/", response_model=TagResponse, status_code=201)
async def create_tag(
    data: TagCreate,
    _: UserDB = Depends(require_admin),
    service: TagService = Depends(get_tag_service),
) -> TagResponse:
    return await service.create(data)


@router.patch("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: UUID,
    data: TagPatch,
    _: UserDB = Depends(require_admin),
    service: TagService = Depends(get_tag_service),
) -> TagResponse:
    return await service.update(tag_id, data)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: UUID,
    _: UserDB = Depends(require_admin),
    service: TagService = Depends(get_tag_service),
) -> None:
    await service.delete(tag_id)
