"""Gateway tests: subprocess mocked, HTTP contract exercised end to end.

Run from this directory: pip install fastapi httpx pytest && pytest
"""

import base64
import io
import subprocess
import threading
from unittest.mock import MagicMock, patch

import main
import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer s3cret"}


def completed(stdout=b"", stderr=b"", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class FakeProc:
    """Stand-in for the Popen the exec endpoint drives."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, hangs=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self._hangs = hangs
        self.killed = False

    def wait(self, timeout=None):
        if self._hangs and not self.killed:
            raise subprocess.TimeoutExpired(cmd="sandbox", timeout=timeout)
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "SECRET", "s3cret")
    return TestClient(main.app)


class TestAuth:
    def test_missing_token_rejected(self, client):
        response = client.post("/sandboxes", json={"sandbox_id": "sbx-x"})
        assert response.status_code == 401

    def test_unconfigured_secret_fails_closed(self, monkeypatch):
        monkeypatch.setattr(main, "SECRET", None)
        client = TestClient(main.app)
        response = client.post("/sandboxes", json={"sandbox_id": "sbx-x"}, headers=AUTH)
        assert response.status_code == 503

    def test_health_needs_no_token(self, client):
        assert client.get("/health").status_code == 200


class TestLaunch:
    def test_launch_argv(self, client):
        with patch("main.subprocess.run") as run:
            run.return_value = completed()
            response = client.post(
                "/sandboxes", json={"sandbox_id": "sbx-x"}, headers=AUTH
            )

        assert response.status_code == 201
        argv = run.call_args.args[0]
        assert argv[:3] == [main.CLI, "run", "sbx-x"]
        assert "--detach" in argv
        assert "--write" in argv

    def test_launch_egress_requires_gateway_optin(self, client, monkeypatch):
        monkeypatch.setattr(main, "ALLOW_EGRESS", False)
        with patch("main.subprocess.run") as run:
            run.return_value = completed()
            client.post(
                "/sandboxes",
                json={"sandbox_id": "sbx-x", "allow_egress": True},
                headers=AUTH,
            )
        assert "--allow-egress" not in run.call_args.args[0]

        monkeypatch.setattr(main, "ALLOW_EGRESS", True)
        with patch("main.subprocess.run") as run:
            run.return_value = completed()
            client.post(
                "/sandboxes",
                json={"sandbox_id": "sbx-x", "allow_egress": True},
                headers=AUTH,
            )
        assert "--allow-egress" in run.call_args.args[0]

    def test_restore_imports_tar_from_raw_body(self, client):
        seen = {}

        def fake_run(argv, **kwargs):
            import_arg = next((a for a in argv if a.startswith("--import-tar=")), None)
            if import_arg:
                with open(import_arg.removeprefix("--import-tar="), "rb") as f:
                    seen["tar"] = f.read()
            return completed()

        with patch("main.subprocess.run", side_effect=fake_run):
            response = client.post(
                "/sandboxes/sbx-x/restore",
                content=b"\x00raw-tar-bytes",
                headers={**AUTH, "Content-Type": "application/x-tar"},
            )
        assert response.status_code == 201
        assert seen["tar"] == b"\x00raw-tar-bytes"

    def test_restore_rejects_empty_body(self, client):
        with patch("main.subprocess.run") as run:
            response = client.post(
                "/sandboxes/sbx-x/restore", content=b"", headers=AUTH
            )
        assert response.status_code == 422
        run.assert_not_called()

    def test_launch_failure_maps_to_502(self, client):
        with patch("main.subprocess.run") as run:
            run.return_value = completed(stderr=b"boom", returncode=1)
            run.return_value.stderr = "boom"
            run.return_value.stdout = ""
            response = client.post(
                "/sandboxes", json={"sandbox_id": "sbx-x"}, headers=AUTH
            )
        assert response.status_code == 502
        assert "boom" in response.json()["detail"]

    def test_flag_like_sandbox_id_rejected(self, client):
        with patch("main.subprocess.run") as run:
            response = client.post(
                "/sandboxes", json={"sandbox_id": "--evil"}, headers=AUTH
            )
        assert response.status_code == 422
        run.assert_not_called()


class TestExec:
    def test_exec_roundtrip(self, client):
        with patch("main.subprocess.Popen") as popen:
            popen.return_value = FakeProc(stdout=b"out", stderr=b"err", returncode=3)
            response = client.post(
                "/sandboxes/sbx-x/exec",
                json={"argv": ["/bin/bash", "-lc", "echo hi"], "timeout": 5},
                headers=AUTH,
            )

        argv = popen.call_args.args[0]
        assert argv == [main.CLI, "exec", "sbx-x", "--", "/bin/bash", "-lc", "echo hi"]
        body = response.json()
        assert base64.b64decode(body["stdout_b64"]) == b"out"
        assert base64.b64decode(body["stderr_b64"]) == b"err"
        assert body["exit_code"] == 3
        assert body["timed_out"] is False
        assert body["truncated"] is False

    def test_exec_timeout_kills_process(self, client):
        proc = FakeProc(hangs=True)
        with patch("main.subprocess.Popen", return_value=proc):
            response = client.post(
                "/sandboxes/sbx-x/exec", json={"argv": ["/bin/true"]}, headers=AUTH
            )
        assert response.status_code == 200
        assert response.json()["timed_out"] is True
        assert proc.killed is True

    def test_exec_stuck_pipe_answers_within_grace(self, client, monkeypatch):
        """A descendant holding the pipe open must not hang the request."""
        monkeypatch.setattr(main, "_READER_GRACE_SECONDS", 0.05)

        class StuckStream:
            def read(self, _size):
                threading.Event().wait()  # never returns

        proc = FakeProc()
        proc.stdout = StuckStream()
        with patch("main.subprocess.Popen", return_value=proc):
            response = client.post(
                "/sandboxes/sbx-x/exec", json={"argv": ["/bin/true"]}, headers=AUTH
            )
        body = response.json()
        assert response.status_code == 200
        assert base64.b64decode(body["stdout_b64"]) == main._TRUNCATION_NOTICE
        assert body["truncated"] is True

    def test_exec_output_capped(self, client):
        oversized = b"x" * (main.MAX_STREAM_BYTES + 1000)
        with patch("main.subprocess.Popen") as popen:
            popen.return_value = FakeProc(stdout=oversized)
            response = client.post(
                "/sandboxes/sbx-x/exec", json={"argv": ["/usr/bin/yes"]}, headers=AUTH
            )
        body = response.json()
        stdout = base64.b64decode(body["stdout_b64"])
        assert body["truncated"] is True
        assert stdout.endswith(main._TRUNCATION_NOTICE)
        assert len(stdout) == main.MAX_STREAM_BYTES + len(main._TRUNCATION_NOTICE)

    def test_invalid_sandbox_id_rejected(self, client):
        with patch("main.subprocess.Popen") as popen:
            response = client.post(
                "/sandboxes/--evil/exec", json={"argv": ["/bin/true"]}, headers=AUTH
            )
        assert response.status_code == 422
        popen.assert_not_called()


class TestTarAndDelete:
    def test_tar_returns_binary(self, client):
        def fake_run(argv, **kwargs):
            export = next(a for a in argv if a.startswith("--file="))
            with open(export.removeprefix("--file="), "wb") as f:
                f.write(b"overlay-tar")
            result = completed()
            result.stderr = ""
            return result

        with patch("main.subprocess.run", side_effect=fake_run):
            response = client.get("/sandboxes/sbx-x/tar", headers=AUTH)

        assert response.status_code == 200
        assert response.content == b"overlay-tar"
        assert response.headers["content-type"] == "application/x-tar"

    def test_delete(self, client):
        with patch("main.subprocess.run") as run:
            run.return_value = completed()
            response = client.delete("/sandboxes/sbx-x", headers=AUTH)

        assert response.status_code == 204
        assert run.call_args.args[0] == [main.CLI, "delete", "sbx-x", "--force"]

    def test_delete_missing_sandbox_is_idempotent(self, client):
        with patch("main.subprocess.run") as run:
            run.return_value = completed(returncode=1)
            run.return_value.stderr = "sandbox sbx-x not found"
            run.return_value.stdout = ""
            response = client.delete("/sandboxes/sbx-x", headers=AUTH)
        assert response.status_code == 204

    def test_delete_failure_maps_to_502(self, client):
        with patch("main.subprocess.run") as run:
            run.return_value = completed(returncode=1)
            run.return_value.stderr = "launcher unreachable"
            run.return_value.stdout = ""
            response = client.delete("/sandboxes/sbx-x", headers=AUTH)
        assert response.status_code == 502
        assert "launcher unreachable" in response.json()["detail"]

    def test_lifecycle_timeout_maps_to_504(self, client):
        with patch("main.subprocess.run") as run:
            run.side_effect = subprocess.TimeoutExpired(cmd="sandbox", timeout=120)
            response = client.get("/sandboxes/sbx-x/tar", headers=AUTH)
        assert response.status_code == 504
