import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.tools import StructuredTool

from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.oauth_events import oauth_completion_key
from app.mcp.client.tools import bound_tool_artifact
from app.runtime.sandbox_mcp.backend import BridgeSandbox
from app.runtime.sandbox_mcp.schemas import CallRequest
from app.runtime.sandbox_mcp.service import key
from app.runtime.sandbox_mcp.worker import BridgeSession
from app.runtime.toolset import AgentTool, Toolset


def setup(approval=False, function=None):
    async def customers():
        return "customers", {"structured_content": {"rows": [{"CustomerID": 42}]}}

    tool = StructuredTool.from_function(
        coroutine=function or customers,
        name="crm_customers",
        description="List customers",
        response_format="content_and_artifact",
    )
    bound_tool_artifact(tool, None)
    resolved = SimpleNamespace(
        live=Toolset([AgentTool(tool=tool, requires_approval=approval)]),
        config=SimpleNamespace(name="CRM agent", mcp_servers=[]),
    )
    thread = SimpleNamespace(id=str(uuid4()), user_id=uuid4())
    backend = MagicMock()
    backend.execute.return_value = SimpleNamespace(exit_code=0)
    backend.upload_files.return_value = [SimpleNamespace(error=None)]
    return BridgeSession(resolved, thread, backend), tool


async def wait_status(session, call, status):
    async with asyncio.timeout(4):
        while True:
            operation = await session.broker.read(session.scope, str(call.id))
            if operation["status"] == status:
                return operation
            if operation["status"] == "error" and status != "error":
                pytest.fail(str(operation))
            await asyncio.sleep(0.01)


async def test_allow_offloads_structured_result_without_changing_direct_calls():
    session, tool = setup()
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        result = await wait_status(session, call, "complete")
        assert "result" not in result  # Redis/logs hold references, not payloads.
        assert result["path"].endswith(f"/{call.id}.json")
        payload = json.loads(session.backend.upload_files.call_args.args[0][0][1])
        assert payload["structured_content"]["rows"][0]["CustomerID"] == 42
        assert payload["is_error"] is False
        direct = await tool.ainvoke(
            {"type": "tool_call", "id": "direct", "name": tool.name, "args": {}}
        )
        assert direct.artifact is None


async def test_disabled_and_cross_agent_tools_are_unavailable():
    session, _ = setup()
    async with session:
        for name in ("disabled_tool", "other_agents_tool"):
            with pytest.raises(HTTPException) as error:
                await session.broker.enqueue(
                    session.scope, CallRequest(id=uuid4(), tool=name)
                )
            assert error.value.status_code == 403
        session.backend.upload_files.assert_not_called()


async def test_approval_is_required_and_only_owner_can_decide():
    session, tool = setup(approval=True)
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        pending = await wait_status(session, call, "approval_required")
        session.backend.upload_files.assert_not_called()
        assert await session.broker.pending(session.thread.id, "another-user") == []
        with pytest.raises(HTTPException) as denied:
            await session.broker.decide(
                session.thread.id,
                "another-user",
                session.scope,
                str(call.id),
                "approve",
                pending["phase"],
            )
        assert denied.value.status_code == 404
        await session.broker.decide(
            session.thread.id,
            str(session.thread.user_id),
            session.scope,
            str(call.id),
            "approve",
            pending["phase"],
        )
        with pytest.raises(HTTPException) as stale:
            await session.broker.decide(
                session.thread.id,
                str(session.thread.user_id),
                session.scope,
                str(call.id),
                "reject",
                pending["phase"],
            )
        assert stale.value.status_code == 409
        await wait_status(session, call, "complete")


async def test_rejection_never_invokes_mcp():
    invoked = AsyncMock(return_value=("done", None))

    async def write():
        return await invoked()

    session, tool = setup(approval=True, function=write)
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        pending = await wait_status(session, call, "approval_required")
        await session.broker.decide(
            session.thread.id,
            str(session.thread.user_id),
            session.scope,
            str(call.id),
            "reject",
            pending["phase"],
        )
        await wait_status(session, call, "error")
        invoked.assert_not_awaited()


async def test_oauth_callback_resumes_only_the_blocked_call():
    invocations = 0

    async def customers():
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise OAuthAuthorizationRequired(
                "https://auth.example/authorize?state=unique-state"
            )
        return "ok", {"structured_content": {"rows": []}}

    session, tool = setup(function=customers)
    session._reconnect = AsyncMock()
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        pending = await wait_status(session, call, "oauth_required")
        assert pending["auth_url"].startswith("https://auth.example/")
        await session.broker.redis.set(
            oauth_completion_key("different-state"), "complete"
        )
        await asyncio.sleep(0.55)
        assert invocations == 1
        await session.broker.redis.set(oauth_completion_key("unique-state"), "complete")
        await wait_status(session, call, "complete")
        assert invocations == 2
        session._reconnect.assert_awaited_once()


async def test_uncertain_network_failure_is_not_retried():
    invoked = AsyncMock(side_effect=TimeoutError("Unknown write outcome"))

    async def write():
        return await invoked()

    session, tool = setup(function=write)
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        await wait_status(session, call, "error")
        await session.broker.enqueue(session.scope, call)
        assert invoked.await_count == 1


async def test_capability_revoked_at_run_end_and_bad_capability_denied():
    session, _ = setup()
    async with session:
        assert (await session.broker.active(session.scope))["user_id"] == str(
            session.thread.user_id
        )
        with pytest.raises(HTTPException):
            await session.broker.active("wrong-capability")
    with pytest.raises(HTTPException) as gone:
        await session.broker.active(session.scope)
    assert gone.value.status_code == 410


async def test_expired_worker_lease_prevents_calls():
    session, tool = setup()
    await session._lease()
    await session.broker.redis.delete(key(session.scope, "lease"))
    with pytest.raises(HTTPException) as gone:
        await session.broker.enqueue(
            session.scope, CallRequest(id=uuid4(), tool=tool.name)
        )
    assert gone.value.status_code == 410


async def test_operation_id_cannot_change_tool_arguments():
    session, tool = setup()
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        with pytest.raises(HTTPException) as collision:
            await session.broker.enqueue(
                session.scope, call.model_copy(update={"arguments": {"other": "input"}})
            )
        assert collision.value.status_code == 409


def test_bridge_credentials_are_injected_below_tool_inputs():
    backend = MagicMock()
    backend.execute.return_value = SimpleNamespace(exit_code=0)
    wrapped = BridgeSandbox(backend, "temporary-capability")
    original = "python3 -c 'print(42)'"
    wrapped.execute(original, timeout=90)
    command = backend.execute.call_args.args[0]
    assert "AUXILIA_MCP_TOKEN=temporary-capability" in command
    assert "auxilia-mcp-sdk" in command
    assert backend.execute.call_args.kwargs["timeout"] == 90
    assert original == "python3 -c 'print(42)'"


async def test_expired_result_cannot_replay_a_call():
    session, tool = setup()
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        await wait_status(session, call, "complete")
        await session.broker.redis.delete(key(session.scope, str(call.id)))
        with pytest.raises(HTTPException) as expired:
            await session.broker.enqueue(session.scope, call)
        assert expired.value.status_code == 409
        assert session.backend.upload_files.call_count == 1


async def test_call_limit_does_not_leave_an_unqueued_operation(monkeypatch):
    from app.runtime.sandbox_mcp.settings import bridge_settings

    monkeypatch.setattr(bridge_settings, "max_calls", 1)
    session, tool = setup()
    async with session:
        await session.broker.enqueue(
            session.scope, CallRequest(id=uuid4(), tool=tool.name)
        )
        second = CallRequest(id=uuid4(), tool=tool.name)
        with pytest.raises(HTTPException) as limited:
            await session.broker.enqueue(session.scope, second)
        assert limited.value.status_code == 429
        assert (
            await session.broker.redis.get(key(session.scope, str(second.id))) is None
        )


async def test_sdk_and_user_endpoints_use_different_authentication(current_user):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    session, tool = setup()
    session.thread.user_id = current_user.id
    async with (
        session,
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as http,
    ):
        assert (await http.get("/sandbox-mcp/tools")).status_code in (401, 403)
        auth = {"Authorization": "Bearer " + session.token}
        tools = await http.get("/sandbox-mcp/tools", headers=auth)
        assert tools.status_code == 200
        assert tool.name in tools.json()
        assert "token" not in tools.text
        denied = await http.post(
            "/sandbox-mcp/calls",
            headers=auth,
            json={"id": str(uuid4()), "tool": "disabled"},
        )
        assert denied.status_code == 403
        call = CallRequest(id=uuid4(), tool=tool.name)
        created = await http.post(
            "/sandbox-mcp/calls", headers=auth, json=call.model_dump(mode="json")
        )
        assert created.status_code == 202
        await wait_status(session, call, "complete")
        result = await http.get(f"/sandbox-mcp/calls/{call.id}", headers=auth)
        assert result.status_code == 200
        assert "auth_url" not in result.json()
        assert "arguments" not in result.json()
        assert "path" in result.json()


async def test_expired_lease_cannot_be_revived():
    session, _ = setup()
    await session._lease()
    await session.broker.redis.delete(key(session.scope, "lease"))
    with pytest.raises(RuntimeError, match="lease expired"):
        await session._lease(renew=True)
    with pytest.raises(HTTPException):
        await session.broker.active(session.scope)


async def test_cancellation_revokes_access_and_never_executes_pending_approval():
    invoked = AsyncMock(return_value=("done", None))

    async def write():
        return await invoked()

    session, tool = setup(approval=True, function=write)
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        await wait_status(session, call, "approval_required")
        await session.close()
        with pytest.raises(HTTPException):
            await session.broker.active(session.scope)
        invoked.assert_not_awaited()
    # close is idempotent; the runtime closes before snapshots and ExitStack too.
    invoked.assert_not_awaited()


def test_sandbox_capability_cannot_answer_user_approval(client):
    response = client.get(
        "/threads/a-thread/sandbox-mcp/pending",
        headers={"Authorization": "Bearer sandbox-capability-is-not-a-user-session"},
    )
    assert response.status_code == 401


def test_automatic_helper_receives_bridge_discovery_instructions():
    from deepagents.profiles.harness.harness_profiles import HarnessProfile

    from app.runtime.harness import _general_purpose_subagent
    from tests.runtime.scripted_model import ScriptedChatModel
    from tests.sandbox.stub_sandbox import StubSandbox

    backend = BridgeSandbox(StubSandbox(), "temporary-token")
    helper = _general_purpose_subagent(
        ScriptedChatModel(script=[]), [], backend, HarnessProfile()
    )
    assert helper is not None
    assert "import auxilia_mcp as mcp" in helper["system_prompt"]
    assert "print(mcp.tools())" in helper["system_prompt"]
    assert "temporary-token" not in helper["system_prompt"]


def test_main_agent_receives_bridge_discovery_instructions():
    from unittest.mock import patch

    from app.runtime.agent import build_runnable
    from tests.runtime.scripted_model import ScriptedChatModel
    from tests.sandbox.stub_sandbox import StubSandbox

    backend = BridgeSandbox(StubSandbox(), "temporary-token")
    with patch("app.runtime.agent.create_agent") as create:
        build_runnable(
            model=ScriptedChatModel(script=[]),
            tools=[],
            system_prompt="Main agent",
            sandbox_backend=backend,
        )
    prompt = create.call_args.kwargs["system_prompt"]
    assert "import auxilia_mcp as mcp" in prompt
    assert "print(mcp.tools())" in prompt
    assert "temporary-token" not in prompt


async def test_expired_queue_entry_does_not_stop_other_calls(monkeypatch):
    session, tool = setup()
    consume = session._consume
    gate = asyncio.Event()

    async def delayed_consume():
        await gate.wait()
        await consume()

    monkeypatch.setattr(session, "_consume", delayed_consume)
    async with session:
        expired = CallRequest(id=uuid4(), tool=tool.name)
        healthy = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, expired)
        await session.broker.enqueue(session.scope, healthy)
        await session.broker.redis.delete(key(session.scope, str(expired.id)))
        gate.set()
        await wait_status(session, healthy, "complete")
        assert await session.broker.active(session.scope)
        assert session.backend.upload_files.call_count == 1


async def test_write_never_resurrects_expired_operation(monkeypatch):
    from app.runtime.sandbox_mcp.service import _UPDATE

    session, tool = setup()
    await session._lease()
    call = CallRequest(id=uuid4(), tool=tool.name)
    await session.broker.enqueue(session.scope, call)
    evaluate = session.broker.redis.eval

    async def expire_before_update(script, *args):
        if script == _UPDATE:
            await session.broker.redis.delete(key(session.scope, str(call.id)))
        return await evaluate(script, *args)

    monkeypatch.setattr(session.broker.redis, "eval", expire_before_update)
    with pytest.raises(HTTPException) as expired:
        await session.broker.write(session.scope, str(call.id), {"status": "complete"})
    assert expired.value.status_code == 404
    assert await session.broker.redis.get(key(session.scope, str(call.id))) is None
    with pytest.raises(HTTPException) as replay:
        await session.broker.enqueue(session.scope, call)
    assert replay.value.status_code == 409


async def test_late_decision_is_rejected_after_waiter_stops():
    session, tool = setup(approval=True)
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        pending = await wait_status(session, call, "approval_required")
        await session.broker.redis.delete(key(session.scope, "pending"))
        with pytest.raises(HTTPException) as stale:
            await session.broker.decide(
                session.thread.id,
                str(session.thread.user_id),
                session.scope,
                str(call.id),
                "approve",
                pending["phase"],
            )
        assert stale.value.status_code == 409
        assert (
            await session.broker.redis.get(
                key(session.scope, f"decision:{call.id}:{pending['phase']}")
            )
            is None
        )


async def test_reconnect_closes_owned_replacement_before_opening_next(monkeypatch):
    from contextlib import asynccontextmanager

    session, _ = setup()
    events = []

    @asynccontextmanager
    async def db():
        yield None

    @asynccontextmanager
    async def opened(prepared):
        events.append(("open", prepared))
        try:
            yield session.resolved.live
        finally:
            events.append(("close", prepared))

    monkeypatch.setattr("app.runtime.sandbox_mcp.worker.AsyncSessionLocal", db)
    monkeypatch.setattr(Toolset, "prepare", AsyncMock(side_effect=["first", "second"]))
    monkeypatch.setattr(Toolset, "open", opened)
    await session._reconnect()
    await session._reconnect()
    assert events == [("open", "first"), ("close", "first"), ("open", "second")]
    await session.close()
    assert events[-1] == ("close", "second")


async def test_cleanup_failure_does_not_skip_later_bridges_or_snapshot():
    from app.runtime.agent import Agent

    agent = object.__new__(Agent)
    first = SimpleNamespace(
        close=AsyncMock(side_effect=RuntimeError("transport close failed"))
    )
    second = SimpleNamespace(close=AsyncMock())
    agent._bridges = [first, second]
    agent._persist_sandbox = AsyncMock()
    await agent._finish_sandbox()
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()
    agent._persist_sandbox.assert_awaited_once()


async def test_sdk_result_endpoint_only_exposes_its_contract(current_user):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    session, tool = setup()
    async with session:
        call = CallRequest(id=uuid4(), tool=tool.name)
        await session.broker.enqueue(session.scope, call)
        await wait_status(session, call, "complete")
        await session.broker.write(
            session.scope,
            str(call.id),
            {
                "future_private_field": "must stay private",
                "auth_url": "https://auth.example",
            },
        )
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as http:
            response = await http.get(
                f"/sandbox-mcp/calls/{call.id}",
                headers={"Authorization": "Bearer " + session.token},
            )
        assert set(response.json()) == {"status", "path"}


def test_provider_bash_semantics_and_existing_pythonpath_are_preserved(
    tmp_path, monkeypatch
):
    import os
    import subprocess

    from deepagents.backends.protocol import ExecuteResponse

    from app.runtime.sandbox_mcp.backend import SDK_ROOT

    backend = MagicMock()

    def execute(command, **kwargs):
        result = subprocess.run(
            ["/bin/bash", "-c", command],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "/existing/python/path"},
        )
        return ExecuteResponse(
            output=result.stdout + result.stderr, exit_code=result.returncode
        )

    backend.execute.side_effect = execute
    result = BridgeSandbox(backend, "temporary-token").execute(
        '[[ 2 -eq 2 ]] && printf "%s" "$PYTHONPATH"'
    )
    assert result.exit_code == 0
    assert result.output == SDK_ROOT + ":/existing/python/path"
