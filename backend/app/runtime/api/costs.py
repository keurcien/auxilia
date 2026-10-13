"""Read-only cost estimates from retained usage and the current catalog."""

from decimal import Decimal
from typing import Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.database import get_checkpointer
from app.exceptions import NotFoundError
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.runtime.checkpoints import iter_checkpoint_messages


class MessageCost(BaseModel):
    message_id: str | None
    model_id: str | None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    input_cost: Decimal | None = None
    cached_input_cost: Decimal | None = None
    output_cost: Decimal | None = None
    total_cost: Decimal | None = None
    reason: Literal["missing_usage", "missing_pricing", "invalid_usage"] | None = None


class ConversationCost(BaseModel):
    thread_id: str
    currency: Literal["USD"] = "USD"
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
    result.input_tokens = input_tokens
    result.cached_input_tokens = cached
    result.output_tokens = output_tokens
    model = catalog.get(model_id) if model_id else None
    if model is None or model.pricing is None:
        result.reason = "missing_pricing"
        return result
    pricing = model.pricing
    million = Decimal(1_000_000)
    result.input_cost = Decimal(input_tokens - cached) * pricing.input_cost / million
    result.cached_input_cost = Decimal(cached) * pricing.cached_input_cost / million
    result.output_cost = Decimal(output_tokens) * pricing.output_cost / million
    result.total_cost = (
        result.input_cost + result.cached_input_cost + result.output_cost
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
        complete = all(cost.total_cost is not None for cost in costs)
        known = sum((cost.total_cost or Decimal(0) for cost in costs), Decimal(0))
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
