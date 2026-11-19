from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import Response

from app.appearance.schemas import (
    InstanceAppearancePatch,
    InstanceAppearanceResponse,
)
from app.appearance.service import (
    InstanceAppearanceService,
    get_instance_appearance_service,
)
from app.auth.dependencies import require_admin
from app.exceptions import NotFoundError
from app.users.models import UserDB
from app.utils.images import (
    image_response,
    process_notification_badge,
    process_uploaded_image,
)


router = APIRouter(prefix="/appearance", tags=["appearance"])


@router.get("/", response_model=InstanceAppearanceResponse)
async def get_instance_appearance(
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.get_settings()


@router.patch("/", response_model=InstanceAppearanceResponse)
async def update_instance_appearance(
    data: InstanceAppearancePatch,
    _: UserDB = Depends(require_admin),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.update_name(data.app_name)


@router.get("/logo")
async def get_instance_logo(
    if_none_match: str | None = Header(default=None),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> Response:
    row = await service.get_logo()
    if (
        row is None
        or row.logo_data is None
        or row.logo_media_type is None
        or row.logo_sha256 is None
    ):
        raise NotFoundError("Instance logo not found")
    return image_response(
        data=row.logo_data,
        media_type=row.logo_media_type,
        digest=row.logo_sha256,
        if_none_match=if_none_match,
    )


@router.put("/logo", response_model=InstanceAppearanceResponse)
async def upload_instance_logo(
    image: UploadFile = File(...),
    _: UserDB = Depends(require_admin),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.set_logo(await process_uploaded_image(image))


@router.delete("/logo", response_model=InstanceAppearanceResponse)
async def delete_instance_logo(
    _: UserDB = Depends(require_admin),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.delete_logo()


@router.get("/notification-badge")
async def get_notification_badge(
    if_none_match: str | None = Header(default=None),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> Response:
    row = await service.get_notification_badge()
    if (
        row is None
        or row.notification_badge_data is None
        or row.notification_badge_media_type is None
        or row.notification_badge_sha256 is None
    ):
        raise NotFoundError("Notification badge not found")
    return image_response(
        data=row.notification_badge_data,
        media_type=row.notification_badge_media_type,
        digest=row.notification_badge_sha256,
        if_none_match=if_none_match,
    )


@router.put("/notification-badge", response_model=InstanceAppearanceResponse)
async def upload_notification_badge(
    image: UploadFile = File(...),
    _: UserDB = Depends(require_admin),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.set_notification_badge(await process_notification_badge(image))


@router.delete("/notification-badge", response_model=InstanceAppearanceResponse)
async def delete_notification_badge(
    _: UserDB = Depends(require_admin),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> InstanceAppearanceResponse:
    return await service.delete_notification_badge()


@router.get("/notification-badge/{revision}")
async def get_notification_badge_revision(
    revision: UUID,
    if_none_match: str | None = Header(default=None),
    service: InstanceAppearanceService = Depends(get_instance_appearance_service),
) -> Response:
    row = await service.get_notification_badge()
    if (
        row is None
        or row.notification_badge_revision != revision
        or row.notification_badge_data is None
        or row.notification_badge_media_type is None
        or row.notification_badge_sha256 is None
    ):
        raise NotFoundError("Notification badge not found")
    return image_response(
        data=row.notification_badge_data,
        media_type=row.notification_badge_media_type,
        digest=row.notification_badge_sha256,
        if_none_match=if_none_match,
    )
