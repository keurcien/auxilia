"""Dependency-free client copied into sandboxes; never contains MCP credentials.

The sandbox backend supplies a per-agent run capability in the environment.
Only explicitly printed results enter model context. Keep an operation ID to
recover an uncertain call without dispatching the same action twice.
"""

import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4


class BridgeTransportError(RuntimeError):
    """The bridge could not be reached or its response could not be read."""


class BridgeHTTPError(RuntimeError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"MCP bridge HTTP {status}: {detail}")


class MCPCallError(RuntimeError):
    def __init__(self, message, operation_id):
        self.operation_id = operation_id
        super().__init__(
            f"{message} (operation_id={operation_id}). Reuse this ID to recover; do not repeat an uncertain write with a new ID."
        )


class MCPCallTimeout(TimeoutError):
    def __init__(self, operation_id):
        self.operation_id = operation_id
        super().__init__(
            f"MCP call timed out (operation_id={operation_id}); reuse this ID to recover before repeating a write"
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(path, body=None, *, timeout=30):
    try:
        url = os.environ["AUXILIA_MCP_URL"].rstrip("/") + "/sandbox-mcp/" + path
        headers = {"Authorization": "Bearer " + os.environ["AUXILIA_MCP_TOKEN"]}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        # Do not forward a capability through an HTTP redirect.
        with urllib.request.build_opener(_NoRedirect).open(
            request, timeout=timeout
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BridgeHTTPError(
            exc.code, exc.read(2000).decode(errors="replace")
        ) from None
    except KeyError as exc:
        raise RuntimeError(f"MCP bridge environment is missing {exc.args[0]}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BridgeTransportError(f"MCP bridge transport failed: {exc}") from exc


def tools():
    """Allowed tool names, descriptions, input schemas and approval requirements."""
    return _request("tools")


def call(tool, arguments=None, *, timeout=840, operation_id=None):
    """Call a permitted tool; wait for approval or OAuth when required.

    Supply the same operation_id (a UUID) to recover an uncertain call within
    this active run. Errors expose the ID too. POST is never retried implicitly;
    idempotent result GETs retry transient failures within the timeout.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    operation_id = (
        str(UUID(str(operation_id))) if operation_id is not None else str(uuid4())
    )
    deadline = time.monotonic() + timeout
    try:
        _request(
            "calls",
            {
                "id": operation_id,
                "tool": tool,
                "arguments": arguments if arguments is not None else {},
            },
            timeout=min(30, timeout),
        )
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                operation = _request(
                    "calls/" + operation_id, timeout=min(30, remaining)
                )
            except BridgeTransportError:
                pass  # Retrying this GET cannot dispatch another MCP call.
            except BridgeHTTPError as exc:
                if exc.status not in (408, 429) and exc.status < 500:
                    raise
            else:
                if operation["status"] == "complete":
                    return json.loads(
                        Path(operation["path"]).read_text(encoding="utf-8")
                    )
                if operation["status"] == "error":
                    raise RuntimeError(operation["error"])
            time.sleep(max(0, min(0.5, deadline - time.monotonic())))
    except (RuntimeError, OSError, ValueError) as exc:
        raise MCPCallError(str(exc), operation_id) from exc
    raise MCPCallTimeout(operation_id)


def call_to_file(tool, arguments, path, *, timeout=840, operation_id=None):
    """Invoke once and save its result, subject to the bridge's result-size limit.

    The operation ID is fixed here so a failed local save still reports it:
    recover with the same ID rather than calling the tool again.
    """
    operation_id = (
        str(UUID(str(operation_id))) if operation_id is not None else str(uuid4())
    )
    result = call(tool, arguments, timeout=timeout, operation_id=operation_id)
    try:
        Path(path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise MCPCallError(
            f"MCP call completed but saving {path} failed: {exc}", operation_id
        ) from exc
    return str(path)
