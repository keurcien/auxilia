import zipfile
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, UploadFile
from pydantic import ValidationError
from starlette.responses import Response

from app.auth.dependencies import get_current_user
from app.exceptions import DomainValidationError
from app.skills.bundles import export_bundle, import_bundle, parse_skill, skill_markdown
from app.skills.schemas import (
    MAX_BUNDLE_BYTES,
    SkillResponse,
    SkillSave,
)
from app.skills.service import SkillService, get_skill_service
from app.users.models import UserDB


router = APIRouter(tags=["skills"])


@router.get("/skills/", response_model=list[SkillResponse])
async def list_skills(
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.list(user)


@router.post("/skills/", response_model=SkillResponse, status_code=201)
async def create_skill(
    data: SkillSave,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.save(data, user)


@router.post("/skills/import", response_model=SkillResponse, status_code=201)
async def import_skill(
    file: UploadFile,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    content = await file.read(MAX_BUNDLE_BYTES + 1)
    try:
        bundle = import_bundle(content, file.filename or "skill.zip")
    except (
        ValueError,
        UnicodeError,
        ValidationError,
        zipfile.BadZipFile,
        yaml.YAMLError,
    ) as exc:
        raise DomainValidationError(str(exc)) from exc
    return await service.save(
        SkillSave(content=skill_markdown(bundle), files=bundle.files), user
    )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.response(await service.authorize(skill_id, user), user)


@router.put("/skills/{skill_id}", response_model=SkillResponse)
async def save_skill(
    skill_id: UUID,
    data: SkillSave,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.save(data, user, skill_id)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    await service.delete(skill_id, user)


@router.get("/skills/{skill_id}/export")
async def export_skill(
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    skill = await service.response(await service.authorize(skill_id, user), user)
    bundle = parse_skill(skill.content, skill.files)
    return Response(
        export_bundle(bundle),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle.name}.zip"'},
    )


@router.get("/agents/{agent_id}/skills")
async def agent_skills(
    agent_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    return await service.attachments(agent_id, user)


@router.put("/agents/{agent_id}/skills/{skill_id}", status_code=204)
async def attach_skill(
    agent_id: UUID,
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    await service.attach(agent_id, skill_id, user)


@router.delete("/agents/{agent_id}/skills/{skill_id}", status_code=204)
async def detach_skill(
    agent_id: UUID,
    skill_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: SkillService = Depends(get_skill_service),
):
    await service.detach(agent_id, skill_id, user)
