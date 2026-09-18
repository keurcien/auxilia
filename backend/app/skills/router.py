from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.skills.schemas import (
    SkillDiffResponse,
    SkillResponse,
    SkillSave,
    SkillSummary,
)
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


@router.get("/{skill_id}/diff", response_model=SkillDiffResponse)
async def diff_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.diff(skill_id, user)


@router.post("/{skill_id}/adopt", response_model=SkillResponse)
async def adopt_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.adopt(skill_id, user)
