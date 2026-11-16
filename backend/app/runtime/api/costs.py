"""Read-only cost estimates from retained usage and current catalog prices."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import aclosing
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import Depends
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Overwrite
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError, NotFoundError
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.runtime.api.protocol_repository import CheckpointWriteRepository
from app.runtime.checkpoints import checkpoint_thread_id


class UsageDetails(BaseModel):
    input: int
    input_cache_read: int
    input_cache_creation: int = 0
    output: int
    total: int


class CostDetails(BaseModel):
    input: Decimal
    input_cache_read: Decimal
    input_cache_creation: Decimal = Decimal(0)
    output: Decimal
    total: Decimal


BUCKETS = ("input", "input_cache_read", "input_cache_creation", "output", "total")


class MessageCost(BaseModel):
    message_id: str | None
    model_id: str | None
    usage_details: UsageDetails | None = None
    cost_details: CostDetails | None = None
    reason: Literal["missing_usage", "missing_pricing", "invalid_usage"] | None = None


class ConversationCost(BaseModel):
    thread_id: str
    complete: bool
    # Null if any call cannot be priced; known_cost is explicitly a subtotal.
    total_cost: Decimal | None
    known_cost: Decimal
    call_count: int = 0
    unpriced_call_count: int = 0
    usage_details: UsageDetails = Field(
        default_factory=lambda: UsageDetails(
            input=0, input_cache_read=0, input_cache_creation=0, output=0, total=0
        )
    )
    # Per-bucket sum over priced calls only; its total equals known_cost.
    cost_details: CostDetails = Field(
        default_factory=lambda: CostDetails(
            input=Decimal(0),
            input_cache_read=Decimal(0),
            input_cache_creation=Decimal(0),
            output=Decimal(0),
            total=Decimal(0),
        )
    )
    messages: list[MessageCost] = Field(default_factory=list)


def _retained_usage(message: AIMessage) -> dict[str, Any] | None:
    if message.usage_metadata:
        return dict(message.usage_metadata)
    raw = message.response_metadata.get("token_usage") or message.response_metadata.get(
        "usage"
    )
    if raw is not None and hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return None
    input_tokens = raw.get("prompt_tokens", raw.get("input_tokens"))
    output_tokens = raw.get("completion_tokens", raw.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    prompt_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details")
    if prompt_details is not None and hasattr(prompt_details, "model_dump"):
        prompt_details = prompt_details.model_dump()
    cached = (
        prompt_details.get("cached_tokens", 0)
        if isinstance(prompt_details, dict)
        else raw.get("cache_read_input_tokens", 0)
    )
    cache_creation = raw.get("cache_creation_input_tokens", 0)
    if cached is None:
        cached = 0
    if cache_creation is None:
        cache_creation = 0
    creation_details = raw.get("cache_creation")
    if creation_details is not None and hasattr(creation_details, "model_dump"):
        creation_details = creation_details.model_dump()
    ephemeral_5m = (
        creation_details.get("ephemeral_5m_input_tokens", 0)
        if isinstance(creation_details, dict)
        else 0
    )
    ephemeral_1h = (
        creation_details.get("ephemeral_1h_input_tokens", 0)
        if isinstance(creation_details, dict)
        else 0
    )
    if ephemeral_5m is None:
        ephemeral_5m = 0
    if ephemeral_1h is None:
        ephemeral_1h = 0
    creation_counts = (cache_creation, ephemeral_5m, ephemeral_1h)
    normalized_creation = (
        max(cache_creation, ephemeral_5m + ephemeral_1h)
        if all(type(count) is int for count in creation_counts)
        else cache_creation
    )
    if (
        "prompt_tokens" not in raw
        and (
            "cache_read_input_tokens" in raw
            or "cache_creation_input_tokens" in raw
            or "cache_creation" in raw
        )
        and type(input_tokens) is int
        and type(cached) is int
        and type(normalized_creation) is int
    ):
        # Anthropic reports uncached, cache-read and cache-created input as
        # disjoint counters. Normalize to LangChain's total-input contract;
        # message_cost splits them again to apply the three different rates.
        input_tokens += cached + normalized_creation
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_token_details": {
            "cache_read": cached,
            "cache_creation": cache_creation,
            "ephemeral_5m_input_tokens": ephemeral_5m,
            "ephemeral_1h_input_tokens": ephemeral_1h,
        },
    }


def _catalog_id_for_reported_model(
    reported: str, catalog: dict[str, SupportedModel]
) -> str:
    if reported in catalog:
        return reported
    versioned_candidates = [
        candidate
        for candidate in catalog
        if reported.startswith(f"{candidate}-")
        and reported[len(candidate) + 1 : len(candidate) + 2].isdigit()
    ]
    return max(versioned_candidates, key=len) if versioned_candidates else reported


def message_cost(
    message: AIMessage, model_id: str | None, catalog: dict[str, SupportedModel]
) -> MessageCost:
    # Prefer a known response model (for example, a differently configured
    # subagent). Versioned names of the pinned model retain the pinned rate;
    # unrelated unknown names stay unpriced.
    reported = message.response_metadata.get(
        "model_name"
    ) or message.response_metadata.get("model")
    if isinstance(reported, str):
        model_id = _catalog_id_for_reported_model(reported, catalog)
    result = MessageCost(message_id=message.id, model_id=model_id)
    usage = _retained_usage(message)
    if not usage:
        result.reason = "missing_usage"
        return result
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    # Plain dict: ephemeral_* keys are outside the TypedDict and validated below.
    details: dict[str, Any] = dict(usage.get("input_token_details") or {})
    cached = details.get("cache_read", 0)
    # langchain-anthropic reports writes as cache_creation or as per-TTL
    # ephemeral splits, depending on version. The same tokens appear either way.
    ephemeral = [
        details.get("ephemeral_5m_input_tokens", 0),
        details.get("ephemeral_1h_input_tokens", 0),
    ]
    counts = (
        input_tokens,
        output_tokens,
        cached,
        details.get("cache_creation", 0),
        *ephemeral,
    )
    if any(type(count) is not int or count < 0 for count in counts):
        result.reason = "invalid_usage"
        return result
    input_count = cast(int, input_tokens)
    output_count = cast(int, output_tokens)
    cached_count = cast(int, cached)
    cache_creation = cast(int, details.get("cache_creation", 0))
    ephemeral_counts = cast(list[int], ephemeral)
    written = max(cache_creation, sum(ephemeral_counts))
    if cached_count + written > input_count:
        result.reason = "invalid_usage"
        return result
    result.usage_details = UsageDetails(
        input=input_count - cached_count - written,
        input_cache_read=cached_count,
        input_cache_creation=written,
        output=output_count,
        total=input_count + output_count,
    )
    model = catalog.get(model_id) if model_id else None
    if model is None or model.prices is None:
        result.reason = "missing_pricing"
        return result
    prices = model.prices
    write_rate = (
        prices.input
        if prices.input_cache_creation is None
        else prices.input_cache_creation
    )
    input_cost = Decimal(input_count - cached_count - written) * prices.input
    cached_input_cost = Decimal(cached_count) * prices.input_cache_read
    cache_write_cost = Decimal(written) * write_rate
    output_cost = Decimal(output_count) * prices.output
    result.cost_details = CostDetails(
        input=input_cost,
        input_cache_read=cached_input_cost,
        input_cache_creation=cache_write_cost,
        output=output_cost,
        total=input_cost + cached_input_cost + cache_write_cost + output_cost,
    )
    return result


_SERDE = JsonPlusSerializer()


def decode_message_write(type_tag: str, blob: bytes) -> list[AIMessage]:
    value = _SERDE.loads_typed((type_tag, blob))
    if isinstance(value, Overwrite):
        value = value.value
    if isinstance(value, BaseMessage):
        value = [value]
    return (
        [message for message in value if isinstance(message, AIMessage)]
        if isinstance(value, list)
        else []
    )


async def iter_cost_messages(
    db: AsyncSession, internal_thread_id: str, pause_seconds: float = 0
) -> AsyncGenerator[AIMessage, None]:
    """Stream task writes once on the request connection.

    Decode off the event loop and optionally pause between small chunks. This
    reads retained root and subagent writes, including compacted messages.
    """
    count = 0
    async with aclosing(
        CheckpointWriteRepository(db).iter_message_writes(
            internal_thread_id, newest_first=not bool(pause_seconds)
        )
    ) as writes:
        async for type_tag, blob in writes:
            for message in await asyncio.to_thread(
                decode_message_write, type_tag, blob
            ):
                yield message
            count += 1
            if pause_seconds and count % 16 == 0:
                await asyncio.sleep(pause_seconds)
    if count == 0 and await db.scalar(
        text("SELECT 1 FROM checkpoints WHERE thread_id = :thread_id LIMIT 1"),
        {"thread_id": internal_thread_id},
    ):
        raise DomainValidationError(
            "Retained checkpoints exist but message writes are unavailable; "
            "cost cannot be reconstructed safely"
        )


class CostService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def conversation(
        self,
        workspace_id: UUID,
        thread_id: str,
        model_id: str | None,
        *,
        catalog: dict[str, SupportedModel] | None = None,
        pause_seconds: float = 0,
    ) -> ConversationCost:
        if catalog is None:
            catalog = {model.model_id: model for model in await get_whitelist()}
        internal_thread_id = checkpoint_thread_id(workspace_id, thread_id)
        costs_by_id: dict[str, MessageCost] = {}
        async with aclosing(
            iter_cost_messages(self.db, internal_thread_id, pause_seconds)
        ) as messages:
            async for message in messages:
                key = (
                    message.id
                    or hashlib.sha256(message.model_dump_json().encode()).hexdigest()
                )
                if key not in costs_by_id or (
                    costs_by_id[key].reason == "missing_usage"
                    and _retained_usage(message)
                ):
                    costs_by_id[key] = message_cost(message, model_id, catalog)
        costs = list(costs_by_id.values())
        complete = all(cost.cost_details is not None for cost in costs)
        known = sum(
            (
                cost.cost_details.total
                for cost in costs
                if cost.cost_details is not None
            ),
            Decimal(0),
        )
        return ConversationCost(
            thread_id=thread_id,
            complete=complete,
            total_cost=known if complete else None,
            known_cost=known,
            call_count=len(costs),
            unpriced_call_count=sum(cost.cost_details is None for cost in costs),
            usage_details=UsageDetails(
                **{
                    name: sum(
                        getattr(cost.usage_details, name)
                        for cost in costs
                        if cost.usage_details is not None
                    )
                    for name in BUCKETS
                }
            ),
            cost_details=CostDetails(
                **{
                    name: sum(
                        (
                            getattr(cost.cost_details, name)
                            for cost in costs
                            if cost.cost_details is not None
                        ),
                        Decimal(0),
                    )
                    for name in BUCKETS
                }
            ),
            messages=costs,
        )

    async def message(
        self,
        workspace_id: UUID,
        thread_id: str,
        model_id: str | None,
        message_id: str,
    ) -> MessageCost:
        conversation = await self.conversation(workspace_id, thread_id, model_id)
        for message in conversation.messages:
            if message.message_id == message_id:
                return message
        raise NotFoundError("Assistant message not found")


def get_cost_service(db: AsyncSession = Depends(get_db)) -> CostService:
    return CostService(db)
