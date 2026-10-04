import asyncio
from uuid import uuid4

import pytest
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.integrations.langfuse.callback import LangfuseLease
from app.integrations.langfuse.tracing import LangfuseTracing
from tests.runtime.test_agent_behaviour import (
    build_agent,
    collect,
    in_memory_runtime,  # noqa: F401 — shared real-runtime fixture
)


pytestmark = pytest.mark.usefixtures("in_memory_runtime")


@pytest.fixture
def exported_tracing():
    """Real SDK, entirely in memory: never send test traces to a server."""
    exporter = InMemorySpanExporter()
    key = f"pk-test-{uuid4()}"
    client = Langfuse(
        public_key=key,
        secret_key="sk-test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    adapter = LangfuseTracing(LangfuseLease(key, CallbackHandler(public_key=key)))
    try:
        yield adapter, client, exporter
    finally:
        client.shutdown()


@pytest.mark.asyncio
async def test_generation_spans_keep_session_ids_across_concurrent_runs(
    exported_tracing,
):
    """Session totals sum generation costs by session ID, not root trace links."""
    adapter, client, exporter = exported_tracing
    agents = []
    for index in range(2):
        agent, model = build_agent(script=["done"])
        agent.thread.id = f"thread-{index}"
        agent.thread.user_id = f"user-{index}"
        model.metadata = {"ls_model_name": f"test-model-{index}"}
        agent.tracing = adapter
        agents.append(agent)

    await asyncio.gather(*(collect(agent) for agent in agents))
    client.flush()
    spans = exporter.get_finished_spans()
    generations = [
        s
        for s in spans
        if s.attributes.get("langfuse.observation.type") == "generation"
    ]
    assert len(generations) == 2
    assert {
        (
            s.attributes.get("session.id"),
            s.attributes.get("user.id"),
            s.attributes.get("langfuse.observation.model.name"),
        )
        for s in generations
    } == {
        ("thread-0", "user-0", "test-model-0"),
        ("thread-1", "user-1", "test-model-1"),
    }
    for generation in generations:
        root = next(
            s
            for s in spans
            if s.parent is None and s.context.trace_id == generation.context.trace_id
        )
        assert root.attributes["session.id"] == generation.attributes["session.id"]
    assert otel_context.get_value("langfuse.propagated.session_id") is None


@pytest.mark.asyncio
async def test_run_without_tracing_does_not_export_spans(exported_tracing):
    _, client, exporter = exported_tracing
    agent, _ = build_agent(script=["works without tracing"])
    assert any("works without tracing" in chunk for chunk in await collect(agent))
    client.flush()
    assert exporter.get_finished_spans() == ()


@pytest.mark.asyncio
async def test_cancellation_releases_propagated_attributes(exported_tracing):
    adapter, client, exporter = exported_tracing
    agent, _ = build_agent(script=["done"])
    agent.tracing = adapter
    with pytest.raises(asyncio.CancelledError):
        async with agent._setup({"messages": []}, None, None, None):
            assert (
                otel_context.get_value("langfuse.propagated.session_id") == "thread-1"
            )
            raise asyncio.CancelledError
    assert otel_context.get_value("langfuse.propagated.session_id") is None
    client.flush()
    assert exporter.get_finished_spans() == ()
