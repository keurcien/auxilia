"""Live recording: a LangChain callback that writes one ledger row per model call.

Attached to the run config, so it sees every chat model call of the graph,
subagents and the tool-discovery router included, whether or not the call's
message ends up in the checkpoint.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.runtime.api.costs import message_cost
from app.threads.models import ThreadDB, ThreadSource
from app.triggers.models import TriggerDB, TriggerType
from app.usage.models import UsageChannel
from app.usage.repository import UsageRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageAttribution:
    """Who and what a thread's model calls are charged to."""

    workspace_id: UUID
    thread_id: str
    user_id: UUID
    agent_id: UUID
    project_id: UUID | None
    trigger_id: UUID | None
    channel: UsageChannel
    model_id: str | None

    @classmethod
    async def for_thread(cls, db: AsyncSession, thread: ThreadDB) -> UsageAttribution:
        return cls(
            workspace_id=thread.workspace_id,
            thread_id=thread.id,
            user_id=thread.user_id,
            agent_id=thread.agent_id,
            project_id=thread.project_id,
            trigger_id=thread.trigger_id,
            channel=await _channel(db, thread),
            model_id=thread.model_id,
        )


async def _channel(db: AsyncSession, thread: ThreadDB) -> UsageChannel:
    # `source` is a plain String column: rows load it back as `str`.
    source = ThreadSource(thread.source)
    if source is not ThreadSource.trigger:
        return UsageChannel(source.value)
    if thread.trigger_id is None:
        return UsageChannel.trigger
    stmt = select(TriggerDB.trigger_type).where(TriggerDB.id == thread.trigger_id)
    trigger_type = await db.scalar(stmt)
    if trigger_type is None:
        return UsageChannel.trigger
    return UsageChannel(TriggerType(trigger_type).value)


def usage_row(
    message: AIMessage,
    attribution: UsageAttribution,
    catalog: dict[str, SupportedModel],
    occurred_at: datetime,
) -> dict[str, Any] | None:
    """Price one model call; None when the provider reported no usage."""
    cost = message_cost(message, attribution.model_id, catalog)
    if cost.usage_details is None:
        return None
    usage = cost.usage_details
    return {
        "workspace_id": attribution.workspace_id,
        "occurred_at": occurred_at,
        "thread_id": attribution.thread_id,
        "message_id": message.id,
        "user_id": attribution.user_id,
        "agent_id": attribution.agent_id,
        "project_id": attribution.project_id,
        "trigger_id": attribution.trigger_id,
        "channel": attribution.channel.value,
        "model_id": cost.model_id,
        "input_tokens": usage.input,
        "cache_read_tokens": usage.input_cache_read,
        "cache_creation_tokens": usage.input_cache_creation,
        "output_tokens": usage.output,
        "total_tokens": usage.total,
        "cost_usd": cost.cost_details.total if cost.cost_details else None,
    }


async def load_catalog() -> dict[str, SupportedModel]:
    return {model.model_id: model for model in await get_whitelist()}


class UsageRecorder(AsyncCallbackHandler):
    """Records each completed model call; a failure is logged, never raised."""

    raise_error = False

    def __init__(self, attribution: UsageAttribution):
        self.attribution = attribution

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        messages = [
            generation.message
            for generations in response.generations
            for generation in generations
            if isinstance(getattr(generation, "message", None), AIMessage)
        ]
        if not messages:
            return
        try:
            catalog = await load_catalog()
            now = datetime.now(UTC)
            rows = [
                row
                for message in messages
                if (row := usage_row(message, self.attribution, catalog, now))
            ]
            if not rows:
                return
            async with AsyncSessionLocal() as db:
                await UsageRepository(db).insert_many(rows)
                await db.commit()
        except Exception:  # noqa: BLE001 — accounting must never fail a run
            logger.warning(
                "Could not record LLM usage for thread %s",
                self.attribution.thread_id,
                exc_info=True,
            )
