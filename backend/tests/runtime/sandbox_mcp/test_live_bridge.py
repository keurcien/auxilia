"""A real Python process -> HTTP bridge -> live authenticated MCP client.

Like the existing live MCP suite, this test needs permission to bind localhost.
It exercises concurrent sandbox execution and result upload, not a mock SDK.
"""

import asyncio
import json
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
    def execute(self, command, *, timeout=None):
        from deepagents.backends.protocol import ExecuteResponse

        completed = subprocess.run(
            command,
            shell=True,
            executable="/bin/sh",
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return ExecuteResponse(
            output=completed.stdout + completed.stderr, exit_code=completed.returncode
        )

    def upload_files(self, files):
        for path, data in files:
            Path(path).write_bytes(data)
        return super().upload_files(files)


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
                code = 'import auxilia_mcp as mcp; import json; print(json.dumps(mcp.call("crm_widget", {})["structured_content"]))'
                command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
                execution = asyncio.create_task(
                    asyncio.to_thread(wrapped.execute, command, timeout=20)
                )
                try:
                    async with asyncio.timeout(10):
                        while not (  # noqa: ASYNC110 - polling an external operation
                            pending := await bridge.broker.pending(
                                thread.id, str(thread.user_id)
                            )
                        ):
                            await asyncio.sleep(0.01)
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
                finally:
                    if not execution.done():
                        await execution
                    shutil.rmtree(
                        f"/tmp/auxilia-mcp-results/{bridge.scope}", ignore_errors=True
                    )
    finally:
        server.should_exit = True
        await server_task
