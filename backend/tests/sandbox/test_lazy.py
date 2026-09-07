"""Unit tests for the lazy sandbox backend."""

from unittest.mock import MagicMock

import pytest

from app.sandbox.lazy import NOT_CONNECTED_MSG, LazySandboxBackend


def test_disconnected_execute_returns_failed_response():
    """`execute` is reached by the `execute` tool *and* by BaseSandbox helpers
    called from middleware hooks (deepagents 0.7 preflights `awrite` through
    `aexecute`), so it must degrade to a failed command, never raise."""
    backend = LazySandboxBackend()
    assert backend.connected is False

    result = backend.execute("echo hi")

    assert result.exit_code == 1
    assert result.output == NOT_CONNECTED_MSG


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
    # Inherited from BaseSandbox (routes through `execute`), not guarded here.
    assert backend.delete("/f.txt").error


@pytest.mark.asyncio
async def test_disconnected_awrite_returns_error_result():
    """The eviction path calls the async variant. Since deepagents 0.7 it
    preflights through `aexecute` before reaching our `write` guard, so this
    relies on `execute` returning a failed response while disconnected."""
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
    backend.grep("needle", path="/src", glob="*.py", max_count=50)
    inner.grep.assert_called_once_with("needle", path="/src", glob="*.py", max_count=50)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_skill_read_recovers_current_bytes_and_pagination(asynchronous):
    from deepagents.backends.protocol import FileDownloadResponse, ReadResult

    path = "/tmp/auxilia-skills/greeting/hash/scripts/hello.py"
    current = 'def hello():\n    return "hi"\n\nprint(hello())\n'
    inner = MagicMock()
    inner.read.return_value = ReadResult(
        error=f"File '{path}': unexpected server response: invalid JSON"
    )
    inner.download_files.return_value = [
        FileDownloadResponse(path=path, content=current.encode(), error=None)
    ]
    backend = LazySandboxBackend()
    backend.connect(inner)
    # Different from the sandbox file: a fallback must reflect edits.
    backend.skill_files = [(path, b"old script")]
    if asynchronous:
        result = await backend.aread(path, offset=1, limit=2)
    else:
        result = backend.read(path, offset=1, limit=2)
    assert result.error is None
    assert result.file_data["content"] == '    return "hi"\n\n'
    assert (
        result.total_lines,
        result.start_line,
        result.end_line,
        result.next_offset,
    ) == (4, 2, 3, 3)
    inner.download_files.assert_called_once_with([path])
    inner.execute.assert_not_called()


@pytest.mark.parametrize(
    "skill_file,error",
    [
        (True, "File not found"),
        (False, "unexpected server response"),
        (True, None),
    ],
)
def test_skill_read_does_not_retry_other_results(skill_file, error):
    from deepagents.backends.protocol import ReadResult

    inner = MagicMock()
    expected = ReadResult(error=error)
    inner.read.return_value = expected
    backend = LazySandboxBackend()
    backend.connect(inner)
    backend.skill_files = [("/skill.py", b"content")] if skill_file else []
    assert backend.read("/skill.py") is expected
    inner.download_files.assert_not_called()


@pytest.mark.parametrize(
    "content,error", [(None, "permission_denied"), (b"\xff", None)]
)
def test_skill_read_keeps_error_if_native_download_cannot_recover(content, error):
    from deepagents.backends.protocol import FileDownloadResponse, ReadResult

    inner = MagicMock()
    expected = ReadResult(error="unexpected server response")
    inner.read.return_value = expected
    inner.download_files.return_value = [
        FileDownloadResponse(path="/skill.py", content=content, error=error)
    ]
    backend = LazySandboxBackend()
    backend.connect(inner)
    backend.skill_files = [("/skill.py", b"content")]
    assert backend.read("/skill.py") is expected


async def test_disconnected_aread_reports_connection_requirement():
    assert (await LazySandboxBackend().aread("/skill.py")).error == NOT_CONNECTED_MSG


async def test_real_sandbox_parser_failure_recovers_through_file_transfer():
    """Exercise BaseSandbox's actual JSON parser, not a mocked read method."""
    from app.sandbox.cloudrun.backend import CloudRunSandbox
    from app.sandbox.cloudrun.transport import ExecResult

    path = "/tmp/auxilia-skills/greeting/hash/scripts/hello.py"
    source = b'def hello():\n    return "hi"\n\nprint(hello())\n'
    # An unescaped newline inside JSON content makes an otherwise recognizable
    # read payload invalid. Never guess how to repair the serialized content.
    malformed = b'{"encoding":"utf-8","content":"def hello():\n    return \\"hi\\"","total_lines":4,"start_line":1,"end_line":4,"next_offset":null}'
    transport = MagicMock()
    transport.exec.side_effect = [
        ExecResult(stdout=malformed, stderr=b"", returncode=0),
        ExecResult(stdout=source, stderr=b"", returncode=0),
    ]
    backend = LazySandboxBackend()
    backend.connect(CloudRunSandbox("test-sandbox", transport=transport))
    backend.skill_files = [(path, b"previous contents")]
    result = await backend.aread(path)
    assert result.error is None
    assert result.file_data["content"] == source.decode()
    assert result.total_lines == 4
    assert transport.exec.call_args_list[1].args[1] == ["/bin/cat", path]
