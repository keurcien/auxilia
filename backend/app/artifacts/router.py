import re
from urllib.parse import quote
from uuid import UUID

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agents.core.service import AgentService, get_agent_service
from app.artifacts.google_slides import DRIVE_FILE_SCOPE, oauth
from app.artifacts.schemas import ArtifactResponse
from app.artifacts.service import ArtifactService, get_artifact_service
from app.auth.dependencies import get_current_user
from app.auth.settings import auth_settings
from app.exceptions import DomainValidationError, NotFoundError
from app.threads.dependencies import authorize_thread_read
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


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


# Fixed path: Google only redirects to URIs registered on the OAuth client.
SLIDES_CALLBACK = "/artifacts/google-slides/callback"
slides_router = APIRouter(tags=["artifacts"])


def require_google_oauth() -> None:
    if not auth_settings.google_oauth_enabled:
        raise NotFoundError("Google sign-in is not configured")


@router.get(
    "/{artifact_id}/export/slides", dependencies=[Depends(require_google_oauth)]
)
async def export_to_slides(
    thread_id: str,
    artifact_id: UUID,
    request: Request,
    user: UserDB = Depends(get_current_user),
):
    """Browser navigation: asks Google for `drive.file`, then lands on the callback."""
    # authorize_redirect, unrolled to store the export target in Authlib's own
    # state record: tied to this OAuth state, expiring with it, and replaced by
    # the next export (a superseded consent fails cleanly, never swaps files).
    client = oauth.google_drive
    redirect_uri = f"{auth_settings.FRONTEND_URL}/api/backend{SLIDES_CALLBACK}"
    rv = await client.create_authorization_url(
        redirect_uri, login_hint=user.email, include_granted_scopes="true"
    )
    await client.save_authorize_data(
        request,
        redirect_uri=redirect_uri,
        slides_export=[thread_id, str(artifact_id)],
        **rv,
    )
    return RedirectResponse(rv["url"], status_code=302)


def drive_access_needed() -> HTMLResponse:
    return HTMLResponse(
        "<p>Google Drive access is needed to export to Google Slides. "
        "Close this tab and try again.</p>",
        status_code=403,
    )


@slides_router.get(SLIDES_CALLBACK, dependencies=[Depends(require_google_oauth)])
async def export_to_slides_callback(
    request: Request,
    user: UserDB = Depends(get_current_user),
    thread_service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
    service: ArtifactService = Depends(get_artifact_service),
):
    client = oauth.google_drive
    state = request.query_params.get("state")
    data = await client.framework.get_state_data(request.session, state)
    pending = data.get("slides_export") if data else None
    if pending is None:
        raise DomainValidationError(
            "No export in progress. Start it again from the file."
        )
    if request.query_params.get("error"):  # the user cancelled the consent
        await client.framework.clear_state_data(request.session, state)
        return drive_access_needed()
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise DomainValidationError(f"Google sign-in failed: {exc.error}") from exc
    # Google lets the user untick a scope on the consent screen.
    if DRIVE_FILE_SCOPE not in token.get("scope", "").split():
        return drive_access_needed()
    thread_id, artifact_id = pending
    # Re-check: access may have changed during the Google round-trip.
    await authorize_thread_read(thread_id, user, thread_service, agent_service)
    url = await service.export_to_slides(
        thread_id, UUID(artifact_id), token["access_token"]
    )
    return RedirectResponse(url, status_code=302)
