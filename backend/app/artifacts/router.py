import re
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
    after: UUID | None = Query(default=None, description="Last artifact id seen"),
    service: ArtifactService = Depends(get_artifact_service),
) -> list[ArtifactResponse]:
    return await service.list(thread_id, after)


def content_disposition(filename: str) -> str:
    """RFC 6266: an ASCII `filename` fallback plus the UTF-8 `filename*` form."""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "download"
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


@router.get(
    "/{artifact_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
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
            "Content-Disposition": content_disposition(row.filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
