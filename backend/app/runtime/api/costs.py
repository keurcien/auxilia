"""Read-only cost estimates from retained usage and the current catalog."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import aclosing
from decimal import Decimal
from typing import Any, Literal

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
    # Null if any call cannot be priced. known_cost is explicitly a subtotal.
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


def message_cost(
    message: AIMessage, model_id: str | None, catalog: dict[str, SupportedModel]
) -> MessageCost:
    # A known response model takes precedence (e.g. a differently configured
    # subagent). A versioned name of the pinned model (claude-haiku-4-5 →
    # claude-haiku-4-5-20251001) keeps the pinned rate; any other unknown name
    # is a model we have no price for, never the parent's.
    reported = message.response_metadata.get(
        "model_name"
    ) or message.response_metadata.get("model")
    if isinstance(reported, str) and (
        reported in catalog or not (model_id and reported.startswith(model_id))
    ):
        model_id = reported
    result = MessageCost(message_id=message.id, model_id=model_id)
    usage = message.usage_metadata
    if not usage:
        result.reason = "missing_usage"
        return result
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    # Plain dict: the ephemeral_* keys are outside the TypedDict, validated below.
    details: dict[str, Any] = dict(usage.get("input_token_details") or {})
    cached = details.get("cache_read", 0)
    # langchain-anthropic reports writes as `cache_creation` or, depending on
    # the version, only as the per-TTL `ephemeral_*` split. Same tokens either way.
    # shortcut: 1h writes (2x input on Anthropic) are priced as 5m ones; split
    # the rate if agents ever use the 1h TTL.
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
    if any(type(n) is not int or n < 0 for n in counts):
        result.reason = "invalid_usage"
        return result
    written = max(details.get("cache_creation", 0), sum(ephemeral))
    if cached + written > input_tokens:
        result.reason = "invalid_usage"
        return result
    result.usage_details = UsageDetails(
        input=input_tokens - cached - written,
        input_cache_read=cached,
        input_cache_creation=written,
        output=output_tokens,
        total=input_tokens + output_tokens,
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
    input_cost = Decimal(input_tokens - cached - written) * prices.input
    cached_input_cost = Decimal(cached) * prices.input_cache_read
    cache_write_cost = Decimal(written) * write_rate
    output_cost = Decimal(output_tokens) * prices.output
    result.cost_details = CostDetails(
        input=input_cost,
        input_cache_read=cached_input_cost,
        input_cache_creation=cache_write_cost,
        output=output_cost,
        total=input_cost + cached_input_cost + cache_write_cost + output_cost,
    )
    return result


_SERDE = JsonPlusSerializer()


def _decode_write(type_tag: str, blob: bytes) -> list[AIMessage]:
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
    db: AsyncSession, thread_id: str, pause_seconds: float = 0
) -> AsyncGenerator[AIMessage, None]:
    """Stream task writes once, on the caller's connection; no checkpoint pool.

    Decode off the event loop and optionally pause between small chunks. This
    reads retained writes across root/subagents, including compacted messages.
    """
    count = 0
    async with aclosing(
        CheckpointWriteRepository(db).iter_message_writes(
            thread_id, newest_first=not bool(pause_seconds)
        )
    ) as writes:
        async for type_tag, blob in writes:
            for message in await asyncio.to_thread(_decode_write, type_tag, blob):
                yield message
            count += 1
            if pause_seconds and count % 16 == 0:
                await asyncio.sleep(pause_seconds)
    if count == 0 and await db.scalar(
        text("SELECT 1 FROM checkpoints WHERE thread_id = :thread_id LIMIT 1"),
        {"thread_id": thread_id},
    ):
        raise DomainValidationError(
            "Retained checkpoints exist but message writes are unavailable; cost cannot be reconstructed safely"
        )


class CostService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def conversation(
        self,
        thread_id: str,
        model_id: str | None,
        *,
        catalog: dict[str, SupportedModel] | None = None,
        pause_seconds: float = 0,
    ) -> ConversationCost:
        if catalog is None:
            catalog = {model.model_id: model for model in await get_whitelist()}
        costs_by_id: dict[str, MessageCost] = {}
        async with aclosing(
            iter_cost_messages(self.db, thread_id, pause_seconds)
        ) as messages:
            async for message in messages:
                key = (
                    message.id
                    or hashlib.sha256(message.model_dump_json().encode()).hexdigest()
                )
                if key not in costs_by_id or (
                    costs_by_id[key].reason == "missing_usage"
                    and message.usage_metadata
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
        self, thread_id: str, model_id: str | None, message_id: str
    ) -> MessageCost:
        conversation = await self.conversation(thread_id, model_id)
        for message in conversation.messages:
            if message.message_id == message_id:
                return message
        raise NotFoundError("Assistant message not found")


def get_cost_service(db: AsyncSession = Depends(get_db)) -> CostService:
    return CostService(db)
