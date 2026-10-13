"""Read-only cost estimates from retained usage and the current catalog."""

from decimal import Decimal
from typing import Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.database import get_checkpointer
from app.exceptions import NotFoundError
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.runtime.checkpoints import iter_checkpoint_messages


class UsageDetails(BaseModel):
    input: int
    input_cache_read: int
    output: int
    total: int


class CostDetails(BaseModel):
    input: Decimal
    input_cache_read: Decimal
    output: Decimal
    total: Decimal


class MessageCost(BaseModel):
    message_id: str | None
    model_id: str | None
    currency: Literal["EUR"] = "EUR"
    usage_details: UsageDetails | None = None
    cost_details: CostDetails | None = None
    reason: Literal["missing_usage", "missing_pricing", "invalid_usage"] | None = None


class ConversationCost(BaseModel):
    thread_id: str
    currency: Literal["EUR"] = "EUR"
    complete: bool
    # Null if any call cannot be priced. known_cost is explicitly a subtotal.
    total_cost: Decimal | None
    known_cost: Decimal
    messages: list[MessageCost] = Field(default_factory=list)


def message_cost(
    message: AIMessage, model_id: str | None, catalog: dict[str, SupportedModel]
) -> MessageCost:
    # A known response model takes precedence (e.g. a differently configured
    # subagent). Provider-versioned names for a pinned alias fall back to the
    # pinned definition; arbitrary unknown names cannot supply a price.
    reported = message.response_metadata.get(
        "model_name"
    ) or message.response_metadata.get("model")
    if isinstance(reported, str) and reported in catalog:
        model_id = reported
    result = MessageCost(message_id=message.id, model_id=model_id)
    usage = message.usage_metadata
    if not usage:
        result.reason = "missing_usage"
        return result
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    if (
        any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens, cached))
        or cached > input_tokens
    ):
        result.reason = "invalid_usage"
        return result
    result.usage_details = UsageDetails(
        input=input_tokens - cached,
        input_cache_read=cached,
        output=output_tokens,
        total=input_tokens + output_tokens,
    )
    model = catalog.get(model_id) if model_id else None
    if model is None or model.pricing is None:
        result.reason = "missing_pricing"
        return result
    prices = model.pricing.prices
    input_cost = Decimal(input_tokens - cached) * prices.input
    cached_input_cost = Decimal(cached) * prices.input_cache_read
    output_cost = Decimal(output_tokens) * prices.output
    result.cost_details = CostDetails(
        input=input_cost,
        input_cache_read=cached_input_cost,
        output=output_cost,
        total=input_cost + cached_input_cost + output_cost,
    )
    return result


class CostService:
    async def conversation(
        self, thread_id: str, model_id: str | None
    ) -> ConversationCost:
        catalog = {model.model_id: model for model in await get_whitelist()}
        messages: dict[str, AIMessage] = {}
        async with get_checkpointer() as checkpointer:
            async for snapshot in iter_checkpoint_messages(checkpointer, thread_id):
                for message in snapshot:
                    if not isinstance(message, AIMessage):
                        continue
                    # IDs are globally assigned by LangGraph; inherited messages
                    # in child namespaces are the same call, not another charge.
                    # Legacy anonymous messages cannot be identified reliably;
                    # deduplicate their serialized form, and document this limit.
                    key = message.id or message.model_dump_json()
                    if key not in messages or (
                        messages[key].usage_metadata is None and message.usage_metadata
                    ):
                        messages[key] = message
        costs = [
            message_cost(message, model_id, catalog) for message in messages.values()
        ]
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


def get_cost_service() -> CostService:
    return CostService()
