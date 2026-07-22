"""Unit tests for the Cloud Run sandbox backend (transport faked)."""

import base64
import re
from collections import deque

import pytest

from app.sandbox.cloudrun.backend import CloudRunSandbox
from app.sandbox.cloudrun.provider import CloudRunProvider
from app.sandbox.cloudrun.transport import ExecResult, SandboxTimeoutError
from app.sandbox.settings import sandbox_settings


class FakeTransport:
    def __init__(self):
        self.exec_calls = []
        self.exec_results = deque()
        self.default_result = ExecResult(stdout=b"", stderr=b"", returncode=0)
        self.launched = []
        self.deleted = []
        self.tar = b"overlay-tar"

    def queue(self, *results):
        self.exec_results.extend(results)

    def launch(self, sandbox_id, *, allow_egress=False, import_tar=None):
        self.launched.append((sandbox_id, allow_egress, import_tar))

    def exec(self, sandbox_id, argv, *, timeout):
        self.exec_calls.append((sandbox_id, argv, timeout))
        if self.exec_results:
            result = self.exec_results.popleft()
            if isinstance(result, Exception):
                raise result
            return result
        return self.default_result

    def export_tar(self, sandbox_id):
        return self.tar

    def delete(self, sandbox_id):
        self.deleted.append(sandbox_id)


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def backend(transport):
    return CloudRunSandbox("sbx-test", timeout=60, transport=transport)


class TestSandboxId:
    def test_rejects_flag_like_id(self, transport):
        with pytest.raises(ValueError):
            CloudRunSandbox("--evil", transport=transport)

    def test_rejects_id_with_spaces(self, transport):
        with pytest.raises(ValueError):
            CloudRunSandbox("a b", transport=transport)

    def test_accepts_generated_shape(self, transport):
        assert CloudRunSandbox("sbx-abc123", transport=transport).id == "sbx-abc123"


class TestExecute:
    def test_runs_command_through_bash(self, backend, transport):
        transport.queue(ExecResult(stdout=b"out", stderr=b"err", returncode=3))
        response = backend.execute("echo hi")

        sandbox_id, argv, timeout = transport.exec_calls[0]
        assert sandbox_id == "sbx-test"
        assert argv == ["/bin/bash", "-lc", "echo hi"]
        assert timeout == 60
        assert response.output == "outerr"
        assert response.exit_code == 3

    def test_timeout_maps_to_124(self, backend, transport):
        transport.queue(SandboxTimeoutError())
        response = backend.execute("sleep 10", timeout=5)

        assert response.exit_code == 124
        assert "timed out after 5 seconds" in response.output

    def test_binary_output_replaced_not_raised(self, backend, transport):
        transport.queue(ExecResult(stdout=b"\xff\xfe", stderr=b"", returncode=0))
        response = backend.execute("cat /bin/true")
        assert response.exit_code == 0


class TestDownloadFiles:
    def test_reads_file_bytes(self, backend, transport):
        transport.queue(ExecResult(stdout=b"\x00binary", stderr=b"", returncode=0))
        [response] = backend.download_files(["/tmp/f.bin"])

        assert response.content == b"\x00binary"
        assert response.error is None
        assert transport.exec_calls[0][1] == ["/bin/cat", "/tmp/f.bin"]

    def test_missing_file(self, backend, transport):
        transport.queue(ExecResult(stdout=b"", stderr=b"no such file", returncode=1))
        [response] = backend.download_files(["/tmp/missing"])
        assert response.error == "file_not_found"

    def test_relative_path_rejected_without_exec(self, backend, transport):
        [response] = backend.download_files(["relative.txt"])
        assert response.error == "invalid_path"
        assert transport.exec_calls == []


class TestUploadFiles:
    def _decode_uploaded(self, transport) -> bytes:
        """Reassemble the file content from the base64 chunks in commands."""
        payload = b""
        for _, argv, _ in transport.exec_calls:
            match = re.search(r"printf '%s' '([^']*)'", argv[-1])
            payload += base64.b64decode(match.group(1))
        return payload

    def test_single_chunk_roundtrip(self, backend, transport):
        [response] = backend.upload_files([("/tmp/a.txt", b"hello")])

        assert response.error is None
        command = transport.exec_calls[0][1][-1]
        assert command.startswith("mkdir -p /tmp && ")
        assert "-d > /tmp/a.txt" in command
        assert self._decode_uploaded(transport) == b"hello"

    def test_large_content_chunks_and_appends(self, backend, transport):
        content = bytes(range(256)) * 512  # 128 KiB > one 48 KiB b64 chunk
        [response] = backend.upload_files([("/tmp/big.bin", content)])

        assert response.error is None
        assert len(transport.exec_calls) > 1
        commands = [argv[-1] for _, argv, _ in transport.exec_calls]
        assert "-d > /tmp/big.bin" in commands[0]
        assert all("-d >> /tmp/big.bin" in c for c in commands[1:])
        assert self._decode_uploaded(transport) == content

    def test_write_failure(self, backend, transport):
        transport.queue(ExecResult(stdout=b"", stderr=b"denied", returncode=1))
        [response] = backend.upload_files([("/etc/ro.txt", b"x")])
        assert response.error == "permission_denied"

    def test_relative_path_rejected(self, backend, transport):
        [response] = backend.upload_files([("rel.txt", b"x")])
        assert response.error == "invalid_path"


class TestProvider:
    @pytest.fixture
    def provider(self, transport, monkeypatch):
        monkeypatch.setattr(
            "app.sandbox.cloudrun.provider.get_transport", lambda: transport
        )
        return CloudRunProvider()

    def test_create_launches_and_returns_message(self, provider, transport):
        backend, message = provider.create(timeout_minutes=30)

        [(sandbox_id, allow_egress, import_tar)] = transport.launched
        assert backend.id == sandbox_id
        assert sandbox_id.startswith("sbx-")
        assert allow_egress is False
        assert import_tar is None
        assert sandbox_id in message

    def test_create_installs_default_packages(self, provider, transport, monkeypatch):
        monkeypatch.setattr(
            sandbox_settings.cloudrun, "default_packages", ["httpx", "rich"]
        )
        provider.create(timeout_minutes=30)

        [(_, argv, _)] = transport.exec_calls
        assert argv[-1] == "pip install httpx rich"

    def test_create_passes_egress_setting(self, provider, transport, monkeypatch):
        monkeypatch.setattr(sandbox_settings.cloudrun, "allow_egress", True)
        provider.create(timeout_minutes=30)
        assert transport.launched[0][1] is True

    def test_create_deletes_sandbox_when_install_fails(
        self, provider, transport, monkeypatch
    ):
        monkeypatch.setattr(sandbox_settings.cloudrun, "default_packages", ["httpx"])
        transport.queue(ExecResult(stdout=b"", stderr=b"no network", returncode=1))

        with pytest.raises(RuntimeError, match="default packages"):
            provider.create(timeout_minutes=30)

        [(sandbox_id, _, _)] = transport.launched
        assert transport.deleted == [sandbox_id]

    def test_connect_alive_fast_path(self, provider, transport):
        backend, message = provider.connect("sbx-x")

        assert backend.id == "sbx-x"
        assert "Reconnected" in message
        assert transport.launched == []

    def test_connect_restores_from_snapshot(self, provider, transport, monkeypatch):
        transport.queue(RuntimeError("not running"))  # is_alive probe fails
        monkeypatch.setattr(
            "app.sandbox.cloudrun.provider.snapshots.load_snapshot", lambda _: b"tar"
        )
        backend, message = provider.connect("sbx-old")

        assert backend.id == "sbx-old"
        assert "Restored" in message
        assert transport.launched[0] == ("sbx-old", False, b"tar")

    def test_connect_without_snapshot_raises(self, provider, transport, monkeypatch):
        transport.queue(ExecResult(stdout=b"", stderr=b"", returncode=1))
        monkeypatch.setattr(
            "app.sandbox.cloudrun.provider.snapshots.load_snapshot", lambda _: None
        )
        with pytest.raises(RuntimeError, match="no snapshot"):
            provider.connect("sbx-gone")


class TestLifecycle:
    def test_is_alive(self, backend, transport):
        assert backend.is_alive() is True
        transport.queue(ExecResult(stdout=b"", stderr=b"", returncode=1))
        assert backend.is_alive() is False
        transport.queue(RuntimeError("gateway unreachable"))
        assert backend.is_alive() is False

    def test_snapshot_returns_overlay_tar(self, backend):
        assert backend.snapshot() == b"overlay-tar"

    def test_persist_uploads_snapshot(self, backend, monkeypatch):
        monkeypatch.setattr(sandbox_settings.cloudrun, "gcs_bucket", "bucket")
        saved = {}
        monkeypatch.setattr(
            "app.sandbox.cloudrun.backend.snapshots.save_snapshot",
            lambda sandbox_id, tar: saved.update({sandbox_id: tar}),
        )
        backend.persist()
        assert saved == {"sbx-test": b"overlay-tar"}

    def test_persist_skips_without_bucket(self, backend, monkeypatch):
        monkeypatch.setattr(sandbox_settings.cloudrun, "gcs_bucket", None)
        monkeypatch.setattr(
            "app.sandbox.cloudrun.backend.snapshots.save_snapshot",
            lambda *a: pytest.fail("should not upload"),
        )
        backend.persist()

    def test_delete(self, backend, transport):
        backend.delete()
        assert transport.deleted == ["sbx-test"]
