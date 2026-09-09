from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response

from app.auth.dependencies import get_current_user
from app.skills.bundles import import_archive
from app.skills.schemas import MAX_BUNDLE_BYTES, SkillResponse, SkillSave, SkillSummary
from app.skills.service import SkillService, get_skill_service
from app.users.models import UserDB


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/", response_model=list[SkillSummary])
async def list_skills(
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.list_summaries(user)


@router.post("/", response_model=SkillResponse, status_code=201)
async def create_skill(
    data: SkillSave,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.create(data, user)


@router.post("/import", response_model=SkillResponse, status_code=201)
async def import_skill(
    file: UploadFile,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    # One byte past the cap is enough for `import_archive` to refuse it.
    data = await file.read(MAX_BUNDLE_BYTES + 1)
    bundle = import_archive(data, file.filename or "skill.zip")
    return await service.create(
        SkillSave(content=bundle.content, files=bundle.files), user
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.get(skill_id, user)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: UUID,
    data: SkillSave,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.update(skill_id, data, user)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    await service.delete(skill_id, user)


@router.get("/{skill_id}/export")
async def export_skill(
    skill_id: UUID,
    _: UserDB = Depends(get_current_user),  # any workspace user may export
    service: SkillService = Depends(get_skill_service),
):
    name, archive = await service.export(skill_id)
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )
