import json
from uuid import uuid4

import httpx
import pytest

from app.artifacts.files import PPTX_MIME
from app.artifacts.google_drive import find_export, google_url, upload_converted


async def test_find_export_matches_the_artifact_property():
    artifact_id = uuid4()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["q"])
        return httpx.Response(200, json={"files": [{"id": "slides-1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await find_export(client, artifact_id) == "slides-1"
    assert f"key='auxilia_artifact' and value='{artifact_id}'" in seen[0]
    assert "trashed = false" in seen[0]


async def test_find_export_none_when_no_file():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"files": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await find_export(client, uuid4()) is None


@pytest.mark.parametrize(
    ("mime_type", "google_mime"),
    [
        (PPTX_MIME, "application/vnd.google-apps.presentation"),
        ("text/csv", "application/vnd.google-apps.spreadsheet"),
    ],
)
async def test_upload_converts_and_tags_the_file(mime_type, google_mime):
    artifact_id = uuid4()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200, headers={"Location": "https://upload.example/session?id=1"}
            )
        return httpx.Response(200, json={"id": "slides-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        file_id = await upload_converted(
            client, artifact_id, "Q3 Review", b"file-bytes", mime_type
        )

    assert file_id == "slides-2"
    start, put = requests
    metadata = json.loads(start.content)
    assert metadata["mimeType"] == google_mime
    assert metadata["appProperties"] == {"auxilia_artifact": str(artifact_id)}
    assert start.headers["X-Upload-Content-Type"] == mime_type
    assert str(put.url) == "https://upload.example/session?id=1"
    assert put.content == b"file-bytes"


def test_google_url_opens_the_matching_editor():
    assert google_url(PPTX_MIME, "a") == "https://docs.google.com/presentation/d/a/edit"
    assert (
        google_url("text/csv", "b") == "https://docs.google.com/spreadsheets/d/b/edit"
    )
