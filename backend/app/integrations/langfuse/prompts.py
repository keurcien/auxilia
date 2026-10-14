"""Langfuse prompt registry adapter: an agent's instructions as a Langfuse prompt.

Stateless by design — auxilia stores nothing about the link. The prompt is
named after the agent id, so unplugging Langfuse leaves no trace in the DB.
"""

import asyncio

from langfuse import Langfuse
from langfuse.api import CreateTextPromptRequest, NotFoundError, Prompt_Text
from langfuse.api.core.api_error import ApiError

from app.exceptions import (
    DomainError,
    DomainValidationError,
    NotFoundError as DomainNotFoundError,
)
from app.integrations.langfuse.callback import get_langfuse_client
from app.integrations.langfuse.schemas import LangfusePromptVersion


PRODUCTION = "production"
# Labels sit on versions, but the list endpoint only reports them per prompt,
# so the picker costs one GET per version — capped to the most recent ones.
MAX_VERSIONS = 20
AUTHOR_KEY = "auxilia_published_by"


def _client() -> Langfuse:
    client = get_langfuse_client()
    if client is None:
        raise DomainNotFoundError("Langfuse is not configured")
    return client


def _to_version(prompt: object) -> LangfusePromptVersion:
    if not isinstance(prompt, Prompt_Text):
        raise DomainValidationError(
            "Only text prompts can be used as agent instructions"
        )
    extra = prompt.model_extra or {}
    # Langfuse records API writes as "API"; auxilia keeps the publisher in config.
    config = prompt.config if isinstance(prompt.config, dict) else {}
    created_by = extra.get("createdBy")
    return LangfusePromptVersion(
        version=prompt.version,
        labels=prompt.labels,
        commit_message=prompt.commit_message,
        text=prompt.prompt,
        author=config.get(AUTHOR_KEY) or (created_by if created_by != "API" else None),
        created_at=extra.get("createdAt"),
    )


def _failed(err: ApiError) -> DomainError:
    return DomainError(f"Langfuse request failed ({err.status_code})")


async def get_production(name: str) -> LangfusePromptVersion | None:
    try:
        prompt = await _client().async_api.prompts.get(name, label=PRODUCTION)
    except NotFoundError:
        return None
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def list_versions(name: str) -> list[LangfusePromptVersion]:
    api = _client().async_api
    try:
        page = await api.prompts.list(name=name)
        versions = sorted(
            {v for meta in page.data if meta.name == name for v in meta.versions},
            reverse=True,
        )[:MAX_VERSIONS]
        prompts = await asyncio.gather(
            *(api.prompts.get(name, version=v) for v in versions)
        )
    except ApiError as err:
        raise _failed(err) from err
    return [_to_version(p) for p in prompts if isinstance(p, Prompt_Text)]


async def get_version(name: str, version: int) -> LangfusePromptVersion:
    try:
        prompt = await _client().async_api.prompts.get(name, version=version)
    except NotFoundError as err:
        raise DomainNotFoundError("Prompt version not found") from err
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def create_production(
    name: str, *, text: str, tags: list[str], commit_message: str, author: str | None
) -> LangfusePromptVersion:
    request = CreateTextPromptRequest(
        name=name,
        prompt=text,
        type="text",
        labels=[PRODUCTION],
        tags=tags,
        commit_message=commit_message,
        config={AUTHOR_KEY: author},
    )
    try:
        prompt = await _client().async_api.prompts.create(request=request)
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)


async def label_production(name: str, version: int) -> LangfusePromptVersion:
    try:
        prompt = await _client().async_api.prompt_version.update(
            name, version, new_labels=[PRODUCTION]
        )
    except NotFoundError as err:
        raise DomainNotFoundError("Prompt version not found") from err
    except ApiError as err:
        raise _failed(err) from err
    return _to_version(prompt)
