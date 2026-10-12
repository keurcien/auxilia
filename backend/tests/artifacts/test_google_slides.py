import json
from uuid import uuid4

import httpx

from app.artifacts.google_slides import SLIDES_MIME, find_export, upload_as_slides


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


async def test_upload_converts_and_tags_the_file():
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
        file_id = await upload_as_slides(
            client, artifact_id, "Q3 Review", b"pptx-bytes", "application/x-pptx"
        )

    assert file_id == "slides-2"
    start, put = requests
    metadata = json.loads(start.content)
    assert metadata["mimeType"] == SLIDES_MIME
    assert metadata["appProperties"] == {"auxilia_artifact": str(artifact_id)}
    assert start.headers["X-Upload-Content-Type"] == "application/x-pptx"
    assert str(put.url) == "https://upload.example/session?id=1"
    assert put.content == b"pptx-bytes"
