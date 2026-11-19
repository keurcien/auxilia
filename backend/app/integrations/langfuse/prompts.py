"""Langfuse prompt registry adapter for agent instructions."""

import asyncio

from langfuse import Langfuse
from langfuse.api import CreateTextPromptRequest, NotFoundError, Prompt_Text
from langfuse.api.core.api_error import ApiError

from app.exceptions import (
    DomainError,
    DomainValidationError,
    NotFoundError as DomainNotFoundError,
)
from app.integrations.langfuse.schemas import LangfusePromptVersion


PRODUCTION = "production"
MAX_VERSIONS = 20
AUTHOR_KEY = "auxilia_published_by"


def _to_version(prompt: object) -> LangfusePromptVersion:
    if not isinstance(prompt, Prompt_Text):
        raise DomainValidationError(
            "Only text prompts can be used as agent instructions"
        )
    extra = prompt.model_extra or {}
    config = prompt.config if isinstance(prompt.config, dict) else {}
    created_by = extra.get("createdBy")
    return LangfusePromptVersion(
        version=prompt.version,
        labels=prompt.labels,
        commit_message=prompt.commit_message,
        text=prompt.prompt,
        author=config.get(AUTHOR_KEY) or (created_by if created_by != "API" else None),
        created_at=extra.get("createdAt"),
        public_config={
            key: value for key, value in config.items() if key != AUTHOR_KEY
        },
    )


def _failed(err: ApiError) -> DomainError:
    return DomainError(f"Langfuse request failed ({err.status_code})")


async def get_production(client: Langfuse, name: str) -> LangfusePromptVersion | None:
    try:
        prompt = await client.async_api.prompts.get(name, label=PRODUCTION)
    except NotFoundError:
        return None
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def list_versions(client: Langfuse, name: str) -> list[LangfusePromptVersion]:
    api = client.async_api
    try:
        page = await api.prompts.list(name=name)
        versions = sorted(
            {
                version
                for item in page.data
                if item.name == name
                for version in item.versions
            },
            reverse=True,
        )[:MAX_VERSIONS]
        prompt_versions = await asyncio.gather(
            *(api.prompts.get(name, version=version) for version in versions)
        )
    except ApiError as err:
        raise _failed(err) from err
    return [
        _to_version(prompt)
        for prompt in prompt_versions
        if isinstance(prompt, Prompt_Text)
    ]


async def list_labels(client: Langfuse, name: str) -> list[str]:
    """Return prompt labels except Langfuse's reserved `latest` label."""
    try:
        page = await client.async_api.prompts.list(name=name)
    except ApiError as err:
        raise _failed(err) from err
    labels = {label for item in page.data if item.name == name for label in item.labels}
    return sorted(labels - {"latest"})


async def get_version(
    client: Langfuse, name: str, version: int
) -> LangfusePromptVersion:
    try:
        prompt = await client.async_api.prompts.get(name, version=version)
    except NotFoundError as err:
        raise DomainNotFoundError("Prompt version not found") from err
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def create_version(
    client: Langfuse,
    name: str,
    *,
    text: str,
    label: str,
    tags: list[str],
    commit_message: str,
    config: dict,
) -> LangfusePromptVersion:
    request = CreateTextPromptRequest(
        name=name,
        prompt=text,
        type="text",
        labels=[label],
        tags=tags,
        commit_message=commit_message,
        config=config,
    )
    try:
        prompt = await client.async_api.prompts.create(request=request)
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def label_production(
    client: Langfuse, name: str, version: int
) -> LangfusePromptVersion:
    try:
        prompt = await client.async_api.prompt_version.update(
            name, version, new_labels=[PRODUCTION]
        )
    except NotFoundError as err:
        raise DomainNotFoundError("Prompt version not found") from err
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)
