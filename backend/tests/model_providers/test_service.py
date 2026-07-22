from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.exceptions import (
    DomainValidationError,
    ModelUnavailableError,
    NotFoundError,
)
from app.model_providers.models import ModelDB
from app.model_providers.service import ModelService
from app.model_providers.whitelist import SupportedModel


WHITELIST = [
    SupportedModel(
        provider="anthropic", model_id="claude-sonnet-5", display_name="Claude Sonnet 5"
    ),
    SupportedModel(
        provider="openai", model_id="gpt-4o-mini", display_name="GPT-4o mini"
    ),
    SupportedModel(
        provider="google", model_id="gemini-3-pro-preview", display_name="Gemini 3 Pro"
    ),
]

KEYS = {"anthropic": "anthropic-test-key", "openai": "openai-test-key"}  # no google key


def _service(rows: list[ModelDB]) -> ModelService:
    service = ModelService(AsyncMock())
    service.repository = AsyncMock()
    service.repository.list_all.return_value = rows
    by_key = {(r.provider, r.model_id): r for r in rows}

    async def get_by(
        provider: str, model_id: str, *, for_update: bool = False
    ) -> ModelDB | None:
        return by_key.get((provider, model_id))

    async def get_default(*, for_update: bool = False) -> ModelDB | None:
        return next((r for r in rows if r.is_default), None)

    service.repository.get_by_provider_and_model_id.side_effect = get_by
    service.repository.get_default.side_effect = get_default
    return service


def _row(
    provider: str, model_id: str, is_enabled: bool = True, is_default: bool = False
) -> ModelDB:
    return ModelDB(
        provider=provider,
        model_id=model_id,
        is_enabled=is_enabled,
        is_default=is_default,
    )


@pytest.fixture(autouse=True)
def _patched_sources():
    with (
        patch(
            "app.model_providers.service.get_whitelist",
            AsyncMock(return_value=WHITELIST),
        ),
        patch("app.model_providers.service.provider_api_keys", return_value=KEYS),
    ):
        yield


async def test_ensure_available_resolves_enabled_model():
    service = _service([_row("anthropic", "claude-sonnet-5")])
    resolved = await service.ensure_available("claude-sonnet-5")
    assert resolved.provider == "anthropic"
    assert resolved.api_key == "anthropic-test-key"


@pytest.mark.parametrize(
    ("rows", "model_id", "match"),
    [
        ([], None, "no model is set"),
        ([], "not-a-model", "not in the supported model catalog"),
        # In the whitelist but its provider has no key configured.
        ([_row("google", "gemini-3-pro-preview")], "gemini-3-pro-preview", "API key"),
        # Key configured but no enablement row (absent = disabled)…
        ([], "claude-sonnet-5", "disabled by a workspace admin"),
        # …or an explicit disable.
        (
            [_row("anthropic", "claude-sonnet-5", is_enabled=False)],
            "claude-sonnet-5",
            "disabled by a workspace admin",
        ),
    ],
)
async def test_ensure_available_raises_with_precise_reason(rows, model_id, match):
    service = _service(rows)
    with pytest.raises(ModelUnavailableError, match=match):
        await service.ensure_available(model_id)


async def test_is_available_swallows_the_domain_error():
    service = _service([_row("anthropic", "claude-sonnet-5")])
    assert await service.is_available("claude-sonnet-5") is True
    assert await service.is_available("not-a-model") is False


async def test_list_available_is_the_triple_intersection():
    # gemini is whitelisted+enabled but has no key; gpt-4o-mini has a key but
    # no enablement row — only claude passes whitelist ∧ key ∧ enabled.
    service = _service(
        [_row("anthropic", "claude-sonnet-5"), _row("google", "gemini-3-pro-preview")]
    )
    available = await service.list_available()
    assert [m.model_id for m in available] == ["claude-sonnet-5"]


async def test_set_enabled_rejects_models_outside_the_whitelist():
    service = _service([])
    with pytest.raises(NotFoundError):
        await service.set_enabled("anthropic", "not-a-model", True)


async def test_set_enabled_refuses_to_disable_the_last_available_model():
    service = _service([_row("anthropic", "claude-sonnet-5")])
    with pytest.raises(DomainValidationError, match="last available model"):
        await service.set_enabled("anthropic", "claude-sonnet-5", False)


async def test_set_enabled_creates_the_opt_in_row(tmp_path):
    # Real (SQLite) repository, not a mock: BaseRepository.create validates its
    # input, and a full ModelDB instance fails on its None server timestamps —
    # a mocked create can't catch that (it shipped a 500 once).
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'models.db'}")

    def _create(conn):
        SQLModel.metadata.create_all(conn, tables=[ModelDB.__table__])

    async with engine.begin() as conn:
        await conn.run_sync(_create)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        service = ModelService(db)

        result = await service.set_enabled("openai", "gpt-4o-mini", True)

        assert result.is_enabled is True
        row = await service.repository.get_by_provider_and_model_id(
            "openai", "gpt-4o-mini"
        )
        assert row is not None and row.is_enabled is True
        # Toggling an existing row updates in place instead of duplicating.
        await service.set_enabled("anthropic", "claude-sonnet-5", True)
        result = await service.set_enabled("openai", "gpt-4o-mini", False)
        assert result.is_enabled is False
        assert len(await service.repository.list_all()) == 2
    await engine.dispose()


async def test_set_default_requires_an_available_model():
    # gpt-4o-mini has a key but no enablement row → not available → refused.
    service = _service([_row("anthropic", "claude-sonnet-5")])
    with pytest.raises(ModelUnavailableError, match="disabled by a workspace admin"):
        await service.set_default("openai", "gpt-4o-mini")


async def test_set_default_rejects_a_provider_mismatch():
    # model_id resolves but under a different provider — data-entry error.
    service = _service([_row("anthropic", "claude-sonnet-5")])
    with pytest.raises(NotFoundError):
        await service.set_default("openai", "claude-sonnet-5")


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # The admin's flag wins while its model is available.
        (
            [
                _row("anthropic", "claude-sonnet-5"),
                _row("openai", "gpt-4o-mini", is_default=True),
            ],
            "gpt-4o-mini",
        ),
        # No flag set → first available (whitelist order).
        (
            [_row("anthropic", "claude-sonnet-5"), _row("openai", "gpt-4o-mini")],
            "claude-sonnet-5",
        ),
        # Flagged model became unavailable (provider lost its key) → fallback.
        (
            [
                _row("anthropic", "claude-sonnet-5"),
                _row("google", "gemini-3-pro-preview", is_default=True),
            ],
            "claude-sonnet-5",
        ),
        # Nothing available at all.
        ([], None),
    ],
)
async def test_get_default_model_id_prefers_the_flag_then_falls_back(rows, expected):
    service = _service(rows)
    assert await service.get_default_model_id() == expected


async def test_default_flag_lifecycle(tmp_path):
    # Real (SQLite) repository so the partial unique index and flush ordering
    # are exercised, not mocked.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'models.db'}")

    def _create(conn):
        SQLModel.metadata.create_all(conn, tables=[ModelDB.__table__])

    async with engine.begin() as conn:
        await conn.run_sync(_create)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        service = ModelService(db)
        await service.set_enabled("anthropic", "claude-sonnet-5", True)
        await service.set_enabled("openai", "gpt-4o-mini", True)

        # Setting moves the single flag between rows.
        result = await service.set_default("anthropic", "claude-sonnet-5")
        assert result.is_default is True
        result = await service.set_default("openai", "gpt-4o-mini")
        assert result.is_default is True
        flagged = [r for r in await service.repository.list_all() if r.is_default]
        assert [(r.provider, r.model_id) for r in flagged] == [
            ("openai", "gpt-4o-mini")
        ]

        # Disabling the default auto-unsets it (back to automatic).
        result = await service.set_enabled("openai", "gpt-4o-mini", False)
        assert result.is_default is False
        assert await service.repository.get_default() is None
        assert await service.get_default_model_id() == "claude-sonnet-5"

        # clear_default is a no-op when unset, unsets when set.
        await service.clear_default()
        await service.set_default("anthropic", "claude-sonnet-5")
        await service.clear_default()
        assert await service.repository.get_default() is None
    await engine.dispose()


async def test_list_manage_flags_orphan_rows_as_deprecated():
    # A row whose model left the whitelist is kept and surfaced, never hidden.
    service = _service(
        [_row("anthropic", "claude-sonnet-5"), _row("deepseek", "deepseek-r2")]
    )
    managed = await service.list_manage()
    by_id = {m.model_id: m for m in managed}
    # Whitelist models with a configured key are listed (enabled or not).
    assert by_id["claude-sonnet-5"].is_enabled is True
    assert by_id["gpt-4o-mini"].is_enabled is False
    # No key → not offerable → not listed.
    assert "gemini-3-pro-preview" not in by_id
    assert by_id["deepseek-r2"].deprecated is True
