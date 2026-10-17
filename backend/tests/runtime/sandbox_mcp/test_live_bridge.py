"""A real Python process -> HTTP bridge -> live authenticated MCP client.

Like the existing live MCP suite, this test needs permission to bind localhost.
It exercises concurrent sandbox execution and result upload, not a mock SDK.
"""

import asyncio
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import uvicorn
from fastapi import FastAPI

from app.mcp.client.connection import ConnectionSpec
from app.runtime.sandbox_mcp.backend import BridgeSandbox
from app.runtime.sandbox_mcp.router import router
from app.runtime.sandbox_mcp.worker import SDK_SOURCE, BridgeSession
from app.runtime.toolset import PreparedToolset, Toolset
from tests.mcp.client.test_live_client import (
    live_server as live_server,
)
from tests.sandbox.stub_sandbox import StubSandbox


class ProcessSandbox(StubSandbox):
    def __init__(self):
        super().__init__()
        self.processes = set()

    def execute(self, command, *, timeout=None):
        from deepagents.backends.protocol import ExecuteResponse

        process = subprocess.Popen(
            ["/bin/bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.processes.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
            return ExecuteResponse(output=stdout + stderr, exit_code=process.returncode)
        finally:
            self.processes.discard(process)

    def terminate(self):
        for process in list(self.processes):
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    def upload_files(self, files):
        for path, data in files:
            Path(path).write_bytes(data)
        return super().upload_files(files)


async def wait_for_approval(execution, bridge, thread):
    async with asyncio.timeout(10):
        while True:
            if execution.done():
                result = execution.result()
                pytest.fail(
                    f"Sandbox exited before requesting approval:\n{result.output}"
                )
            pending = await bridge.broker.pending(thread.id, str(thread.user_id))
            if pending:
                return pending
            await asyncio.sleep(0.01)


async def cleanup_execution(execution, backend):
    # Kill only processes owned by this test backend. Do not wait for the
    # subprocess's 20-second timeout or replace the original test failure.
    backend.terminate()
    with suppress(Exception):
        await asyncio.wait_for(asyncio.shield(execution), timeout=2)
    if not execution.done():
        execution.cancel()


async def test_python_process_can_call_mcp_and_wait_for_approval(
    live_server,  # noqa: F811 - imported pytest fixture
    tmp_path,
    monkeypatch,
):
    from app.runtime.sandbox_mcp.settings import bridge_settings

    sdk_dir = tmp_path / "sdk"
    sdk_dir.mkdir()
    (sdk_dir / "auxilia_mcp.py").write_bytes(SDK_SOURCE.read_bytes())
    monkeypatch.setattr("app.runtime.sandbox_mcp.backend.SDK_ROOT", str(sdk_dir))
    http_app = FastAPI()
    http_app.include_router(router)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(http_app, host="127.0.0.1", port=port, log_level="warning")
    )
    server_task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if server_task.done():
                    server_task.result()
                await asyncio.sleep(0.01)
        monkeypatch.setattr(bridge_settings, "url", f"http://127.0.0.1:{port}")
        prepared = PreparedToolset(
            connections={"crm": ConnectionSpec(url=live_server.url)},
            tool_settings={"crm": {"widget": "needs_approval"}},
            server_id_by_name={"crm": str(uuid4())},
            interrupt_on={"crm_widget": True},
            apply_ui=False,
        )
        async with Toolset.open(prepared) as live:
            resolved = SimpleNamespace(
                live=live, config=SimpleNamespace(name="CRM", mcp_servers=[])
            )
            thread = SimpleNamespace(id=str(uuid4()), user_id=uuid4())
            backend = ProcessSandbox()
            async with BridgeSession(resolved, thread, backend) as bridge:
                wrapped = BridgeSandbox(backend, bridge.token)
                operation_id = str(uuid4())
                code = (
                    "import auxilia_mcp as mcp; import json; "
                    f'result = mcp.call("crm_widget", {{}}, operation_id="{operation_id}"); '
                    f'assert mcp.call("crm_widget", {{}}, operation_id="{operation_id}") == result; '
                    'print(json.dumps(result["structured_content"]))'
                )
                command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
                execution = asyncio.create_task(
                    asyncio.to_thread(wrapped.execute, command, timeout=20)
                )
                try:
                    pending = await wait_for_approval(execution, bridge, thread)
                    assert not execution.done()  # The script really waits for the user.
                    request = pending[0]
                    assert request["tool"] == "crm_widget"
                    await bridge.broker.decide(
                        thread.id,
                        str(thread.user_id),
                        bridge.scope,
                        request["id"],
                        "approve",
                        request["phase"],
                    )
                    result = await execution
                    assert result.exit_code == 0, result.output
                    assert json.loads(result.output) == {"rows": [1, 2, 3]}
                    assert (
                        len(backend.uploads) == 1
                    )  # Reusing the ID did not invoke MCP again.
                finally:
                    await cleanup_execution(execution, backend)
                    shutil.rmtree(
                        f"/tmp/auxilia-mcp-results/{bridge.scope}", ignore_errors=True
                    )
    finally:
        server.should_exit = True
        await server_task


async def test_early_script_failure_reports_its_output():
    future = asyncio.get_running_loop().create_future()
    future.set_result(
        SimpleNamespace(output="ModuleNotFoundError: client missing", exit_code=1)
    )
    with pytest.raises(
        pytest.fail.Exception, match="ModuleNotFoundError: client missing"
    ):
        await wait_for_approval(future, None, None)


async def test_cleanup_terminates_a_waiting_script():
    from unittest.mock import MagicMock

    future = asyncio.get_running_loop().create_future()
    backend = MagicMock()
    backend.terminate.side_effect = lambda: future.set_result(
        SimpleNamespace(output="terminated")
    )
    await cleanup_execution(future, backend)
    backend.terminate.assert_called_once()
