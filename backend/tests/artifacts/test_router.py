from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.artifacts.service import get_artifact_service
from app.exceptions import PermissionDeniedError
from app.main import app
from app.threads.dependencies import authorize_thread_read


def test_artifacts_require_authentication(client):
    response = client.get("/threads/private/artifacts")
    assert response.status_code == 401


def test_thread_read_gate_applies_to_listing_and_bytes(client, current_user):
    async def denied():
        raise PermissionDeniedError("Cannot view this thread")

    app.dependency_overrides[authorize_thread_read] = denied
    for suffix in ["", f"/{uuid4()}/content"]:
        assert client.get(f"/threads/private/artifacts{suffix}").status_code == 403


def test_html_download_never_executes_on_app_origin(client):
    app.dependency_overrides[authorize_thread_read] = lambda: None
    service = MagicMock()
    row = MagicMock(filename="report.html")
    service.content = AsyncMock(return_value=(row, b"<script>alert(1)</script>"))
    app.dependency_overrides[get_artifact_service] = lambda: service
    response = client.get(f"/threads/thread/artifacts/{uuid4()}/content")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


def test_download_name_has_ascii_fallback_and_utf8_form():
    from app.artifacts.router import content_disposition

    header = content_disposition('Résumé "final".pptx')
    assert header.startswith('attachment; filename="R_sum_ _final_.pptx"; ')
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%20%22final%22.pptx" in header


def test_viewer_settings_expose_html_sources(client, current_user, monkeypatch):
    monkeypatch.setattr(
        "app.artifacts.router.artifact_settings.html_sources", ["https:"]
    )
    response = client.get("/artifacts/viewer")
    assert response.status_code == 200
    assert response.json() == {"html_sources": ["https:"]}
