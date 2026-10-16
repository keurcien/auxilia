"""Dependency-free client copied into sandboxes; never contains MCP credentials.

The sandbox backend supplies a per-agent run capability in the environment.
Only explicitly printed results enter model context. `call` returns the MCP
content and structured content; `call_to_file` keeps a result on sandbox disk.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


def _request(path, body=None):
    url = os.environ["AUXILIA_MCP_URL"].rstrip("/") + "/sandbox-mcp/" + path
    headers = {"Authorization": "Bearer " + os.environ["AUXILIA_MCP_TOKEN"]}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)

    # Do not forward a capability through an HTTP redirect.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=30
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"MCP bridge HTTP {exc.code}: {exc.read(2000).decode(errors='replace')}"
        ) from None


def tools():
    """Allowed tool names, descriptions, input schemas and approval requirements."""
    return _request("tools")


def call(tool, arguments=None, *, timeout=840):
    """Call a permitted tool; wait for user approval/reconnect when required.

    Calls are not automatically replayed after an ambiguous network failure.
    MCP `is_error` is retained in the result; bridge failures raise RuntimeError.
    """
    operation_id = str(uuid4())
    _request("calls", {"id": operation_id, "tool": tool, "arguments": arguments or {}})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation = _request("calls/" + operation_id)
        if operation["status"] == "complete":
            return json.loads(Path(operation["path"]).read_text(encoding="utf-8"))
        if operation["status"] == "error":
            raise RuntimeError(operation["error"])
        time.sleep(0.5)
    raise TimeoutError(
        "MCP call timed out; do not repeat a write without checking its outcome"
    )


def call_to_file(tool, arguments, path, *, timeout=840):
    result = call(tool, arguments, timeout=timeout)
    Path(path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return str(path)
