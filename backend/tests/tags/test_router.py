from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.tags.models import TagDB


def test_create_tag_as_admin(client: TestClient, mock_db, admin_user):
    """Admin can create a tag."""
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = None  # name available
    mock_db.execute.return_value = name_lookup

    async def mock_refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

    response = client.post("/tags/", json={"name": "Data"})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Data"
    assert "id" in data


def test_create_tag_duplicate_name(client: TestClient, mock_db, admin_user):
    existing = TagDB(
        id=uuid4(),
        name="Data",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = name_lookup

    response = client.post("/tags/", json={"name": "Data"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Tag name already exists"


def test_create_tag_requires_admin(client: TestClient, mock_db):
    """Without an authenticated admin the create endpoint is rejected."""
    response = client.post("/tags/", json={"name": "Data"})
    assert response.status_code in (401, 403)


def test_list_tags(client: TestClient, mock_db, current_user):
    tag1 = TagDB(
        id=uuid4(),
        name="Data",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    tag2 = TagDB(
        id=uuid4(),
        name="Productivity",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [tag1, tag2]
    result.scalars.return_value = scalars
    mock_db.execute.return_value = result

    response = client.get("/tags/")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_delete_tag_as_admin(client: TestClient, mock_db, admin_user):
    tag = TagDB(
        id=uuid4(),
        name="Gone",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = tag
    mock_db.execute.return_value = result

    response = client.delete(f"/tags/{tag.id}")

    assert response.status_code == 204
    mock_db.delete.assert_awaited_once()
