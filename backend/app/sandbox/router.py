from fastapi import APIRouter

from app.sandbox.settings import sandbox_settings

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.get("/status")
async def get_sandbox_status():
    return {"enabled": sandbox_settings.enabled}
