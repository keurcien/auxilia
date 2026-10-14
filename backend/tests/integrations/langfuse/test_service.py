from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import DomainValidationError
from app.integrations.langfuse import prompts
from app.integrations.langfuse.schemas import LangfusePromptVersion
from app.integrations.langfuse.service import LangfusePromptService


AGENT_ID = uuid4()


def _version(version: int, text: str) -> LangfusePromptVersion:
    return LangfusePromptVersion(version=version, labels=["production"], text=text)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> LangfusePromptService:
    svc = LangfusePromptService.__new__(LangfusePromptService)
    agent = SimpleNamespace(id=AGENT_ID, name="Sales", instructions="Be nice.\n")
    svc.agents = SimpleNamespace(get_or_404=AsyncMock(return_value=agent))  # type: ignore[assignment]
    return svc


async def test_get_reports_divergence(service, monkeypatch):
    monkeypatch.setattr(
        prompts, "get_production", AsyncMock(return_value=_version(3, "Be nice."))
    )
    assert (await service.get(AGENT_ID)).diverged is False

    monkeypatch.setattr(
        prompts, "get_production", AsyncMock(return_value=_version(4, "Be rude."))
    )
    assert (await service.get(AGENT_ID)).diverged is True


async def test_get_unmanaged_is_not_diverged(service, monkeypatch):
    monkeypatch.setattr(prompts, "get_production", AsyncMock(return_value=None))
    result = await service.get(AGENT_ID)
    assert result.production is None and result.diverged is False


async def test_publish_defaults_message_and_skips_identical(service, monkeypatch):
    create = AsyncMock(return_value=_version(2, "Be nice.\n"))
    monkeypatch.setattr(prompts, "create_production", create)
    monkeypatch.setattr(prompts, "get_production", AsyncMock(return_value=None))
    user = SimpleNamespace(email="a@b.c")

    await service.publish(AGENT_ID, None, user)
    kwargs = create.await_args.kwargs
    assert (
        kwargs["commit_message"]
        == "Publish first version of Sales - Synced from auxilia"
    )
    assert kwargs["author"] == "a@b.c"
    assert kwargs["tags"] == ["Sales"]

    await service.publish(AGENT_ID, " tweak ", user)
    assert create.await_args.kwargs["commit_message"] == "tweak - Synced from auxilia"

    create.reset_mock()
    monkeypatch.setattr(
        prompts, "get_production", AsyncMock(return_value=_version(2, "Be nice."))
    )
    await service.publish(AGENT_ID, None, user)
    create.assert_not_awaited()


async def test_promote_refuses_a_version_the_agent_does_not_run(service, monkeypatch):
    label = AsyncMock()
    monkeypatch.setattr(prompts, "label_production", label)
    monkeypatch.setattr(
        prompts, "get_version", AsyncMock(return_value=_version(1, "Other"))
    )
    with pytest.raises(DomainValidationError):
        await service.promote(AGENT_ID, 1)
    label.assert_not_awaited()

    monkeypatch.setattr(
        prompts, "get_version", AsyncMock(return_value=_version(1, "Be nice."))
    )
    await service.promote(AGENT_ID, 1)
    label.assert_awaited_once_with(str(AGENT_ID), 1)
