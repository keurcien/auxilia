from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.artifacts.schemas import ArtifactResponse
from app.artifacts.service import ArtifactService, get_artifact_service
from app.threads.dependencies import authorize_thread_read


router = APIRouter(
    prefix="/threads/{thread_id}/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(authorize_thread_read)],
)


@router.get("")
async def list_artifacts(
    thread_id: str,
    offset: int = Query(default=0, ge=0),
    service: ArtifactService = Depends(get_artifact_service),
) -> list[ArtifactResponse]:
    return await service.list(thread_id, offset)


@router.get("/{artifact_id}/content")
async def artifact_content(
    thread_id: str,
    artifact_id: UUID,
    service: ArtifactService = Depends(get_artifact_service),
) -> Response:
    row, data = await service.content(thread_id, artifact_id)
    # Always download at the API surface; only trusted viewers render bytes.
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
