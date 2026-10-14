from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from deepagents.graph import DeepAgentState
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from pydantic import ValidationError

from app.exceptions import NotFoundError, PermissionDeniedError
from app.main import app
from app.model_providers.pricing import TokenPrices
from app.model_providers.whitelist import SupportedModel, parse_whitelist
from app.runtime.api.costs import CostService, get_cost_service, message_cost
from app.runtime.checkpoints import iter_checkpoint_messages
from app.threads.dependencies import authorize_thread_read
from app.threads.models import ThreadDB
from app.threads.service import get_thread_service


def model(**kwargs):
    return SupportedModel(
        provider="openai",
        model_id="test-model",
        display_name="Test",
        prices=TokenPrices(input="2e-6", input_cache_read="0.5e-6", output="8e-6"),
        **kwargs,
    )


def call(id="call-1", **kwargs):
    return AIMessage(
        id=id,
        content="hello",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "input_token_details": {"cache_read": 400},
        },
        **kwargs,
    )


def test_cached_input_is_not_double_charged():
    result = message_cost(call(), "test-model", {"test-model": model()})
    assert result.usage_details.model_dump() == {
        "input": 600,
        "input_cache_read": 400,
        "input_cache_creation": 0,
        "output": 100,
        "total": 1100,
    }
    assert result.cost_details.input == Decimal("0.0012")
    assert result.cost_details.input_cache_read == Decimal("0.0002")
    assert result.cost_details.output == Decimal("0.0008")
    assert result.cost_details.total == Decimal("0.0022")


@pytest.mark.parametrize(
    "details",
    [
        {"cache_read": 400, "cache_creation": 300},
        # Some langchain-anthropic versions only report the per-TTL split.
        {
            "cache_read": 400,
            "cache_creation": 0,
            "ephemeral_5m_input_tokens": 300,
            "ephemeral_1h_input_tokens": 0,
        },
    ],
)
def test_cache_writes_are_their_own_bucket(details):
    message = call()
    message.usage_metadata["input_token_details"] = details
    priced = model()
    priced.prices.input_cache_creation = Decimal("2.5e-6")
    result = message_cost(message, "test-model", {"test-model": priced})
    assert result.usage_details.input == 300
    assert result.usage_details.input_cache_creation == 300
    assert result.cost_details.input_cache_creation == Decimal("0.00075")
    assert result.cost_details.total == Decimal("0.00235")
    # Without a write price, writes cost the plain input rate.
    fallback = message_cost(message, "test-model", {"test-model": model()})
    assert fallback.cost_details.input_cache_creation == Decimal("0.0006")
    assert fallback.cost_details.total == Decimal("0.0022")


def test_cache_reads_and_writes_cannot_exceed_input():
    message = call()
    message.usage_metadata["input_token_details"] = {
        "cache_read": 700,
        "cache_creation": 400,
    }
    result = message_cost(message, "test-model", {"test-model": model()})
    assert result.reason == "invalid_usage" and result.cost_details is None


def test_no_cache_and_reported_model():
    message = call(response_metadata={"model_name": "test-model"})
    message.usage_metadata["input_token_details"] = {}
    result = message_cost(message, "another-model", {"test-model": model()})
    assert result.model_id == "test-model"
    assert result.cost_details.total == Decimal("0.0028")


def test_versioned_names_keep_the_pinned_rate_but_unknown_models_are_unpriced():
    catalog = {"test-model": model()}
    dated = message_cost(
        call(response_metadata={"model_name": "test-model-20251001"}),
        "test-model",
        catalog,
    )
    assert dated.model_id == "test-model" and dated.cost_details is not None
    # A subagent on an unlisted model must not inherit the parent's price.
    other = message_cost(
        call(response_metadata={"model_name": "other-model"}), "test-model", catalog
    )
    assert other.model_id == "other-model" and other.reason == "missing_pricing"
    # No reported name at all: the pinned model prices it.
    assert message_cost(call(), "test-model", catalog).cost_details is not None


def test_missing_usage_and_pricing_are_unknown():
    assert (
        message_cost(AIMessage(content="hi"), "test-model", {}).reason
        == "missing_usage"
    )
    result = message_cost(call(), "removed-model", {})
    assert result.reason == "missing_pricing" and result.cost_details is None
    assert result.usage_details.input_cache_read == 400


def test_invalid_usage_is_not_a_negative_charge():
    message = call()
    message.usage_metadata["input_token_details"]["cache_read"] = 1001
    result = message_cost(message, "test-model", {"test-model": model()})
    assert result.reason == "invalid_usage" and result.cost_details is None


@pytest.mark.parametrize("rate", ["-1", "NaN", "Infinity"])
def test_invalid_rates_rejected(rate):
    with pytest.raises(ValidationError):
        TokenPrices(input=rate, input_cache_read="0", output="1e-6")


def test_whitelist_prices_are_optional_but_complete_when_present():
    document = """schema_version: 1
models:
  - provider: openai
    model_id: test-model
    display_name: Test
"""
    assert parse_whitelist(document)[0].prices is None
    priced = (
        document + "    prices: {input: 2e-6, input_cache_read: 0.5e-6, output: 8e-6}\n"
    )
    assert parse_whitelist(priced)[0].prices == model().prices
    with pytest.raises(ValidationError):
        parse_whitelist(document + "    prices: {input: 2e-6}\n")


@pytest.fixture
def cost_history(monkeypatch):
    class CursorSaver(InMemorySaver):
        """Model the Postgres saver's cursor lock, without a database."""

        listing = False

        async def alist(self, *args, **kwargs):
            self.listing = True
            try:
                async for saved in super().alist(*args, **kwargs):
                    yield saved
            finally:
                self.listing = False

        async def aget_tuple(self, config):
            assert not self.listing, "point read during alist would deadlock Postgres"
            return await super().aget_tuple(config)

    saver = CursorSaver()

    async def history_messages(db, thread_id, pause_seconds=0):
        async for snapshot in iter_checkpoint_messages(saver, thread_id):
            for message in snapshot:
                if isinstance(message, AIMessage):
                    yield message

    monkeypatch.setattr("app.runtime.api.costs.iter_cost_messages", history_messages)
    monkeypatch.setattr(
        "app.runtime.api.costs.get_whitelist", AsyncMock(return_value=[model()])
    )
    return saver


async def save_history(saver, namespace=""):
    def noop(state):
        return {}

    graph = (
        StateGraph(DeepAgentState)
        .add_node("noop", noop)
        .add_edge(START, "noop")
        .compile(checkpointer=saver)
    )
    config = {"configurable": {"thread_id": "thread", "checkpoint_ns": namespace}}
    await graph.ainvoke({"messages": [HumanMessage(content="hi"), call()]}, config)
    await graph.aupdate_state(
        config, {"messages": [RemoveMessage(id="call-1"), call("call-2")]}
    )
    return graph, config


async def test_history_survives_compaction_and_deduplicates(cost_history):
    graph, config = await save_history(cost_history)
    latest = (await graph.aget_state(config)).values["messages"]
    assert "call-1" not in {message.id for message in latest}
    result = await CostService(AsyncMock()).conversation("thread", "test-model")
    assert {message.message_id for message in result.messages} == {"call-1", "call-2"}
    assert result.complete and result.total_cost == Decimal("0.0044")
    assert (await graph.aget_state(config)).values["messages"] == latest
    assert (
        await CostService(AsyncMock()).message("thread", "test-model", "call-1")
    ).cost_details.total == Decimal("0.0022")
    with pytest.raises(NotFoundError):
        await CostService(AsyncMock()).message("thread", "test-model", "missing")


async def test_empty_and_partial_conversations(cost_history):
    empty = await CostService(AsyncMock()).conversation("empty", "test-model")
    assert empty.complete and empty.total_cost == 0 and empty.messages == []
    graph, config = await save_history(cost_history)
    await graph.aupdate_state(
        config, {"messages": [AIMessage(id="unknown", content="hi")]}
    )
    partial = await CostService(AsyncMock()).conversation("thread", "test-model")
    assert not partial.complete and partial.total_cost is None
    assert partial.known_cost == Decimal("0.0044")
    details = partial.cost_details
    assert details.total == partial.known_cost
    assert details.input + details.input_cache_read + details.output == details.total


@pytest.mark.parametrize("path", ["/cost", "/messages/call-1/cost"])
def test_routes_authorize_before_reading_usage(client, current_user, path):
    service = AsyncMock(spec=CostService)
    app.dependency_overrides[get_cost_service] = lambda: service

    async def denied():
        raise PermissionDeniedError("Not authorized to view this thread")

    app.dependency_overrides[authorize_thread_read] = denied
    assert client.get(f"/threads/thread{path}").status_code == 403
    service.conversation.assert_not_awaited()
    service.message.assert_not_awaited()


@pytest.mark.parametrize("path", ["/cost", "/messages/call-1/cost"])
def test_missing_thread_is_404(client, current_user, path):
    service = AsyncMock()
    service.get.side_effect = NotFoundError("Thread not found")
    app.dependency_overrides[get_thread_service] = lambda: service
    assert client.get(f"/threads/missing{path}").status_code == 404


def test_routes_compute_without_database_writes(
    client, current_user, mock_db, cost_history
):
    thread = ThreadDB(
        id="thread", model_id="test-model", user_id=current_user.id, agent_id=uuid4()
    )
    app.dependency_overrides[authorize_thread_read] = lambda: thread
    response = client.get("/threads/thread/cost")
    assert response.status_code == 200
    assert response.json()["total_cost"] == "0"
    assert client.get("/threads/thread/messages/missing/cost").status_code == 404
    mock_db.add.assert_not_called()
    mock_db.flush.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


async def test_message_route_returns_langfuse_details(
    client, current_user, cost_history
):
    await save_history(cost_history)
    thread = ThreadDB(
        id="thread", model_id="test-model", user_id=current_user.id, agent_id=uuid4()
    )
    app.dependency_overrides[authorize_thread_read] = lambda: thread
    response = client.get("/threads/thread/messages/call-1/cost")
    assert response.status_code == 200
    body = response.json()
    assert body["cost_details"] == {
        "input": "0.001200",
        "input_cache_read": "0.0002000",
        "input_cache_creation": "0.000000",
        "output": "0.000800",
        "total": "0.0022000",
    }
    assert body["usage_details"] == {
        "input": 600,
        "input_cache_read": 400,
        "input_cache_creation": 0,
        "output": 100,
        "total": 1100,
    }
