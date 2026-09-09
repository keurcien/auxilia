"""The /skills HTTP surface: status codes and shapes, service mocked."""

import io
import zipfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.exceptions import StaleRevisionError
from app.main import app
from app.skills.schemas import SkillResponse, SkillSummary
from app.skills.service import get_skill_service
from tests.skills.conftest import skill_markdown


def _response(**overrides) -> SkillResponse:
    defaults = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "name": "report",
        "description": "Write a report",
        "revision": 1,
        "file_count": 0,
        "updated_at": datetime.now(UTC),
        "can_edit": True,
        "content": skill_markdown(),
        "files": [],
    }
    return SkillResponse(**{**defaults, **overrides})


@pytest.fixture
def service(current_user):
    svc = MagicMock()
    svc.list_summaries = AsyncMock(
        return_value=[
            SkillSummary(**_response().model_dump(exclude={"content", "files"}))
        ]
    )
    svc.get = AsyncMock(return_value=_response())
    svc.create = AsyncMock(return_value=_response())
    svc.update = AsyncMock(return_value=_response(revision=2))
    svc.delete = AsyncMock()
    svc.export = AsyncMock(return_value=("report", b"PK\x05\x06" + b"\0" * 18))
    app.dependency_overrides[get_skill_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_skill_service, None)


def test_list_returns_summaries(client: TestClient, service):
    response = client.get("/skills/")
    assert response.status_code == 200
    [row] = response.json()
    assert row["name"] == "report" and "content" not in row


def test_create_and_update_pass_the_payload_through(client: TestClient, service):
    body = {"content": skill_markdown(), "files": [{"path": "a.py", "content": "x"}]}
    assert client.post("/skills/", json=body).status_code == 201
    assert service.create.call_args.args[0].files[0].path == "a.py"

    skill_id = uuid4()
    response = client.put(f"/skills/{skill_id}", json={**body, "revision": 1})
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert service.update.call_args.args[1].revision == 1


def test_stale_revision_is_a_409(client: TestClient, service):
    service.update.side_effect = StaleRevisionError("changed")
    response = client.put(
        f"/skills/{uuid4()}", json={"content": skill_markdown(), "revision": 1}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "changed"


def test_invalid_document_is_a_400_with_the_reason(client: TestClient, service):
    from app.exceptions import DomainValidationError

    service.create.side_effect = DomainValidationError("name: bad")
    response = client.post("/skills/", json={"content": "no frontmatter"})
    assert response.status_code == 400
    assert response.json()["detail"] == "name: bad"


def test_import_accepts_a_zip(client: TestClient, service):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("report/SKILL.md", skill_markdown())
        archive.writestr("report/scripts/run.py", "print(1)")
    response = client.post(
        "/skills/import",
        files={"file": ("report.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 201
    save = service.create.call_args.args[0]
    assert save.files[0].path == "scripts/run.py"


def test_import_rejects_garbage_as_400(client: TestClient, service):
    response = client.post(
        "/skills/import", files={"file": ("x.zip", b"nope", "application/zip")}
    )
    assert response.status_code == 400
    service.create.assert_not_called()


def test_export_streams_a_zip_attachment(client: TestClient, service):
    response = client.get(f"/skills/{uuid4()}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="report.zip"' in response.headers["content-disposition"]


def test_delete_is_204(client: TestClient, service):
    assert client.delete(f"/skills/{uuid4()}").status_code == 204


def test_requires_auth(client: TestClient):
    assert client.get("/skills/").status_code == 401
