"""Unit tests for the lazy sandbox backend."""

from unittest.mock import MagicMock

import pytest

from app.sandbox.lazy import NOT_CONNECTED_MSG, LazySandboxBackend


def test_disconnected_execute_raises():
    backend = LazySandboxBackend()
    assert backend.connected is False
    with pytest.raises(RuntimeError, match=NOT_CONNECTED_MSG):
        backend.execute("echo hi")


def test_connected_delegates_execute():
    backend = LazySandboxBackend()
    inner = MagicMock()
    backend.connect(inner)

    backend.execute("echo hi", timeout=5)

    inner.execute.assert_called_once_with("echo hi", timeout=5)


def test_persist_is_noop_when_disconnected():
    LazySandboxBackend().persist()  # must not raise


def test_persist_delegates_when_supported():
    backend = LazySandboxBackend()
    inner = MagicMock()
    backend.connect(inner)

    backend.persist()

    inner.persist.assert_called_once_with()


def test_persist_is_noop_when_backend_lacks_persist():
    backend = LazySandboxBackend()
    inner = MagicMock(spec=["execute", "id", "download_files", "upload_files"])
    backend.connect(inner)

    backend.persist()  # must not raise


def test_disconnected_file_ops_return_error_results():
    """deepagents calls file ops from middleware hooks (large-tool-result and
    conversation-history eviction), OUTSIDE any tool-call wrapper — a raise
    there escapes ToolErrorMiddleware and kills the run. Disconnected file ops
    must return protocol error results so deepagents skips the eviction."""
    backend = LazySandboxBackend()

    assert backend.ls("/").error == NOT_CONNECTED_MSG
    assert backend.read("/f.txt").error == NOT_CONNECTED_MSG
    assert backend.write("/f.txt", "content").error == NOT_CONNECTED_MSG
    assert backend.edit("/f.txt", "a", "b").error == NOT_CONNECTED_MSG
    assert backend.glob("*.txt").error == NOT_CONNECTED_MSG
    assert backend.grep("needle").error == NOT_CONNECTED_MSG


@pytest.mark.asyncio
async def test_disconnected_awrite_returns_error_result():
    """The eviction path calls the async variant; it inherits the guard via
    BackendProtocol's asyncio.to_thread delegation to the sync method."""
    backend = LazySandboxBackend()
    result = await backend.awrite("/large_tool_results/x", "big payload")
    assert result.error == NOT_CONNECTED_MSG


def test_connected_file_ops_delegate():
    backend = LazySandboxBackend()
    inner = MagicMock()
    backend.connect(inner)

    backend.write("/f.txt", "content")
    inner.write.assert_called_once_with("/f.txt", "content")
    backend.read("/f.txt", offset=3, limit=10)
    inner.read.assert_called_once_with("/f.txt", offset=3, limit=10)
    backend.edit("/f.txt", "a", "b", replace_all=True)
    inner.edit.assert_called_once_with("/f.txt", "a", "b", replace_all=True)
    backend.ls("/")
    inner.ls.assert_called_once_with("/")
    backend.glob("*.py", path="/src")
    inner.glob.assert_called_once_with("*.py", path="/src")
    backend.grep("needle", path="/src", glob="*.py")
    inner.grep.assert_called_once_with("needle", path="/src", glob="*.py")
