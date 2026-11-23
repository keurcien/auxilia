"""Export an artifact to Google Slides or Sheets through the user's own Drive.

Uses the sign-in OAuth client with the extra `drive.file` scope, requested on
the first export only. Nothing is persisted: the Google file carries the
artifact id in `appProperties` (private to this OAuth client), which is how a
later export finds it again.
"""

import json
from uuid import UUID

import httpx
from authlib.integrations.starlette_client import OAuth

from app.artifacts.files import PPTX_MIME
from app.auth.settings import auth_settings


DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
# Artifact mime → (Google mime Drive converts it to, URL path, title suffix).
EXPORTS = {
    PPTX_MIME: ("application/vnd.google-apps.presentation", "presentation", ".pptx"),
    "text/csv": ("application/vnd.google-apps.spreadsheet", "spreadsheets", ".csv"),
}
PROPERTY = "auxilia_artifact"
DRIVE = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

oauth = OAuth()
if auth_settings.google_oauth_enabled:
    oauth.register(
        name="google_drive",
        client_id=auth_settings.GOOGLE_CLIENT_ID,
        client_secret=auth_settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": DRIVE_FILE_SCOPE},
    )


def google_url(mime_type: str, file_id: str) -> str:
    return f"https://docs.google.com/{EXPORTS[mime_type][1]}/d/{file_id}/edit"


async def find_export(client: httpx.AsyncClient, artifact_id: UUID) -> str | None:
    """The Google file a previous export created for this artifact, if still live."""
    query = (
        f"appProperties has {{ key='{PROPERTY}' and value='{artifact_id}' }}"
        " and trashed = false"
    )
    response = await client.get(
        DRIVE, params={"q": query, "fields": "files(id)", "pageSize": 1}
    )
    response.raise_for_status()
    files = response.json()["files"]
    return files[0]["id"] if files else None


async def upload_converted(
    client: httpx.AsyncClient,
    artifact_id: UUID,
    name: str,
    data: bytes,
    mime_type: str,
) -> str:
    """Upload the file and let Drive convert it to a Google file; returns its id."""
    # Resumable upload: no 5 MB ceiling, and no hand-built multipart/related body.
    metadata = {
        "name": name,
        "mimeType": EXPORTS[mime_type][0],
        "appProperties": {PROPERTY: str(artifact_id)},
    }
    start = await client.post(
        UPLOAD,
        params={"uploadType": "resumable"},
        content=json.dumps(metadata),
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": mime_type,
        },
    )
    start.raise_for_status()
    done = await client.put(
        start.headers["Location"],
        content=data,
        headers={"Content-Type": mime_type},
    )
    done.raise_for_status()
    return done.json()["id"]
