from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.main import app
from app.model_providers.schemas import ManagedModelResponse, WhitelistSyncResponse
from app.model_providers.service import get_model_service
from app.model_providers.whitelist import SupportedModel


@pytest.fixture
def model_service():
    service = AsyncMock()
    app.dependency_overrides[get_model_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_model_service, None)


def test_get_models_projects_the_picker_shape(client, model_service):
    model_service.list_available.return_value = [
        SupportedModel(
            provider="openrouter",
            model_id="glm-5.2-max",
            display_name="GLM 5.2 (max reasoning)",
            chef="Z.ai",
            chef_slug="z-ai",
        )
    ]

    response = client.get("/model-providers/models")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "GLM 5.2 (max reasoning)",
            "id": "glm-5.2-max",
            "chef": "Z.ai",
            "chefSlug": "z-ai",
            "providers": ["openrouter"],
        }
    ]


def test_manage_requires_admin(client, model_service, current_user):
    response = client.get("/model-providers/models/manage")
    assert response.status_code == 403


def test_manage_lists_models_for_admin(client, model_service, admin_user):
    model_service.list_manage.return_value = [
        ManagedModelResponse(
            provider="anthropic",
            model_id="claude-sonnet-5",
            display_name="Claude Sonnet 5",
            chef="Anthropic",
            chef_slug="anthropic",
            is_enabled=True,
        )
    ]

    response = client.get("/model-providers/models/manage")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["model_id"] == "claude-sonnet-5"
    assert body[0]["deprecated"] is False


def test_set_enabled_passes_the_path_and_body_through(
    client, model_service, admin_user
):
    model_service.set_enabled.return_value = ManagedModelResponse(
        provider="anthropic",
        model_id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        chef="Anthropic",
        chef_slug="anthropic",
        is_enabled=True,
    )

    response = client.put(
        "/model-providers/models/anthropic/claude-opus-4-8",
        json={"is_enabled": True},
    )

    assert response.status_code == 200
    model_service.set_enabled.assert_awaited_once_with(
        "anthropic", "claude-opus-4-8", True
    )


def test_sync_returns_the_diff(client, model_service, admin_user):
    model_service.sync.return_value = WhitelistSyncResponse(
        added=["claude-opus-4-8"],
        removed=[],
        model_count=15,
        fetched_at=datetime.now(UTC),
    )

    response = client.post("/model-providers/whitelist/sync")

    assert response.status_code == 200
    assert response.json()["added"] == ["claude-opus-4-8"]


def test_model_unavailable_error_shape(client, model_service, current_user):
    """The 409 body is machine-readable: clients branch on error, never on
    the human detail string."""
    from app.exceptions import ModelUnavailableError

    model_service.list_available.side_effect = ModelUnavailableError(
        "claude-opus-4-8", "it has been disabled by a workspace admin"
    )

    response = client.get("/model-providers/models")

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "model_unavailable"
    assert body["model_id"] == "claude-opus-4-8"
