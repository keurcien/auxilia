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
