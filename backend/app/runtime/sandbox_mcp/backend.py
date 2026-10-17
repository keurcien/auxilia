"""Supply bridge access below tool tracing, without rewriting model tool calls."""

import shlex

from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox

from app.runtime.sandbox_mcp.settings import bridge_settings
from app.runtime.sandbox_mcp.worker import SDK_ROOT
from app.settings import app_settings


BRIDGE_PROMPT = """
## MCP tools from code
You may either call your MCP tools directly or use them inside sandbox Python.
Both paths use the same allowed tools and require the same user approvals.
`import auxilia_mcp as mcp` is available in executed Python. Use `mcp.tools()`
for exact tool names, descriptions, JSON input schemas and approval requirements.
Before saying an MCP server or tool is unavailable, execute:
    import auxilia_mcp as mcp
    print(mcp.tools())
Use the returned names exactly; do not guess names from the server's display name.
Only tools enabled for this agent are listed. If discovery fails, report the
actual error rather than concluding that sandbox MCP access is unsupported.
`mcp.call(tool_name, arguments)` returns {content, structured_content, is_error}.
Prefer structured_content when present; check is_error. For example:
    import auxilia_mcp as mcp
    result = mcp.call("exact_tool_name", {"argument": "value"})
    print(result["structured_content"])
Use code for loops, filtering and joins; print only relevant summaries. To save
any result, use `mcp.call_to_file(tool_name, arguments, "/tmp/result.json")`.
Approval or OAuth reconnect requests appear to the user while the call waits.
Allow enough execute timeout for those waits. Never inspect or print bridge
environment credentials. An uncertain or timed-out write must not be repeated
without checking its outcome. Direct MCP calls remain available.
"""


class BridgeSandbox(BaseSandbox):
    def __init__(self, backend: BaseSandbox, token: str):
        self.backend = backend
        self._token = token

    @property
    def id(self) -> str:
        return self.backend.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        url = bridge_settings.url or app_settings.backend_url
        environment = {
            "AUXILIA_MCP_URL": url,
            "AUXILIA_MCP_TOKEN": self._token,
            "PYTHONPATH": SDK_ROOT,
        }
        prefix = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in environment.items()
        )
        # Injection happens at the provider seam, so LangChain's tool input,
        # checkpoints and events retain only the original command.
        wrapped = f"env {prefix} /bin/sh -c {shlex.quote(command)}"
        return self.backend.execute(wrapped, timeout=timeout)

    def upload_files(self, files):
        return self.backend.upload_files(files)

    def download_files(self, paths):
        return self.backend.download_files(paths)
