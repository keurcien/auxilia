import json
import urllib.error
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.runtime.sandbox_mcp import client


class Clock:
    def __init__(self):
        self.elapsed = 0

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(client, "time", clock)
    return clock


def test_poll_retries_transient_failure_without_reposting(monkeypatch, tmp_path, clock):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"structured_content": {"rows": [1]}}))
    calls = []

    def request(endpoint, body=None, **kwargs):
        calls.append((endpoint, body))
        if endpoint == "calls":
            return {"status": "queued"}
        if len(calls) == 2:
            raise client.BridgeTransportError("connection reset")
        return {"status": "complete", "path": str(path)}

    monkeypatch.setattr(client, "_request", request)
    result = client.call("write", {}, timeout=3)
    assert result["structured_content"] == {"rows": [1]}
    assert [endpoint for endpoint, _ in calls].count("calls") == 1
    assert calls[1][0] == calls[2][0]
    assert clock.elapsed == 0.5


def test_post_failure_exposes_operation_id_without_retry(monkeypatch):
    calls = []

    def request(endpoint, body=None, **kwargs):
        calls.append(body)
        raise client.BridgeTransportError("POST response lost")

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(client.MCPCallError) as error:
        client.call("write", {"value": 42})
    assert len(calls) == 1
    assert error.value.operation_id == calls[0]["id"]
    assert calls[0]["id"] in str(error.value)


def test_timeout_preserves_explicit_id_and_bounds_get_timeout(monkeypatch, clock):
    operation_id = str(uuid4())
    requests = []

    def request(endpoint, body=None, **kwargs):
        requests.append((endpoint, body, kwargs["timeout"]))
        if endpoint == "calls":
            return {"status": "queued"}
        raise client.BridgeTransportError("offline")

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(client.MCPCallTimeout) as error:
        client.call("write", {}, timeout=0.5, operation_id=operation_id)
    assert error.value.operation_id == operation_id
    assert operation_id in str(error.value)
    assert requests[0][1]["id"] == operation_id
    assert all(timeout <= 0.5 for _, _, timeout in requests)
    assert clock.elapsed == 0.5


def test_retry_uses_the_same_explicit_operation_id(monkeypatch, tmp_path):
    path = tmp_path / "result.json"
    path.write_text('{"value": 42}')
    posted = []

    def request(endpoint, body=None, **kwargs):
        if endpoint == "calls":
            posted.append(body)
            return {"status": "complete"}
        return {"status": "complete", "path": str(path)}

    monkeypatch.setattr(client, "_request", request)
    operation_id = str(uuid4())
    assert client.call("write", {"x": 1}, operation_id=operation_id) == {"value": 42}
    assert client.call("write", {"x": 1}, operation_id=operation_id) == {"value": 42}
    assert posted[0] == posted[1]


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("offline"), OSError("reset"), ValueError("invalid URL")],
)
def test_transport_errors_are_runtime_errors(monkeypatch, failure):
    monkeypatch.setenv("AUXILIA_MCP_URL", "http://bridge.example")
    monkeypatch.setenv("AUXILIA_MCP_TOKEN", "temporary-capability")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        client.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=fail)
    )
    with pytest.raises(RuntimeError, match="transport failed"):
        client.tools()


def test_invalid_operation_id_never_dispatches(monkeypatch):
    from unittest.mock import Mock

    request = Mock()
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ValueError):
        client.call("write", {}, operation_id="not-a-uuid")
    request.assert_not_called()


def _poll(monkeypatch, *responses):
    """Script the POST (first) and each result GET (then) of one `call`."""
    calls = []
    script = list(responses)

    def request(endpoint, body=None, **kwargs):
        calls.append(endpoint)
        if endpoint == "calls":
            return {"status": "queued"}
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(client, "_request", request)
    return calls


def test_poll_client_error_is_not_retried(monkeypatch, clock):
    operation_id = str(uuid4())
    calls = _poll(monkeypatch, client.BridgeHTTPError(410, "Sandbox MCP session ended"))
    with pytest.raises(client.MCPCallError) as error:
        client.call("write", {}, timeout=3, operation_id=operation_id)
    assert error.value.operation_id == operation_id
    assert "HTTP 410" in str(error.value)
    assert calls.count("calls") == 1 and len(calls) == 2


@pytest.mark.parametrize("status", [429, 503])
def test_poll_retries_rate_limits_and_server_errors(
    monkeypatch, tmp_path, clock, status
):
    path = tmp_path / "result.json"
    path.write_text('{"value": 1}')
    calls = _poll(
        monkeypatch,
        client.BridgeHTTPError(status, "later"),
        {"status": "complete", "path": str(path)},
    )
    assert client.call("write", {}, timeout=3) == {"value": 1}
    assert calls.count("calls") == 1 and len(calls) == 3
    assert clock.elapsed == 0.5


def test_error_status_raises_with_the_operation_id(monkeypatch, clock):
    operation_id = str(uuid4())
    _poll(monkeypatch, {"status": "error", "error": "User rejected this tool call"})
    with pytest.raises(client.MCPCallError, match="User rejected") as error:
        client.call("write", {}, timeout=3, operation_id=operation_id)
    assert error.value.operation_id == operation_id


def test_call_to_file_keeps_the_operation_id_when_saving_fails(monkeypatch, tmp_path):
    result = tmp_path / "result.json"
    result.write_text('{"value": 42}')
    posted = []

    def request(endpoint, body=None, **kwargs):
        if endpoint == "calls":
            posted.append(body["id"])
        return {"status": "complete", "path": str(result)}

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(client.MCPCallError, match="saving") as error:
        client.call_to_file("write", {}, tmp_path / "missing-dir" / "out.json")
    assert error.value.operation_id == posted[0]
    assert len(posted) == 1  # the tool is not called again to recover
