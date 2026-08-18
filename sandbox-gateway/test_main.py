"""Gateway tests: subprocess mocked, HTTP contract exercised end to end.

Run from this directory: pip install fastapi httpx pytest && pytest
"""

import base64
import subprocess
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
        with patch("main.subprocess.run") as run:
            run.return_value = completed(stdout=b"out", stderr=b"err", returncode=3)
            response = client.post(
                "/sandboxes/sbx-x/exec",
                json={"argv": ["/bin/bash", "-lc", "echo hi"], "timeout": 5},
                headers=AUTH,
            )

        argv = run.call_args.args[0]
        assert argv == [main.CLI, "exec", "sbx-x", "--", "/bin/bash", "-lc", "echo hi"]
        assert run.call_args.kwargs["timeout"] == 5
        body = response.json()
        assert base64.b64decode(body["stdout_b64"]) == b"out"
        assert base64.b64decode(body["stderr_b64"]) == b"err"
        assert body["exit_code"] == 3
        assert body["timed_out"] is False

    def test_exec_timeout_flag(self, client):
        with patch("main.subprocess.run") as run:
            run.side_effect = subprocess.TimeoutExpired(cmd="sandbox", timeout=5)
            response = client.post(
                "/sandboxes/sbx-x/exec", json={"argv": ["/bin/true"]}, headers=AUTH
            )
        assert response.status_code == 200
        assert response.json()["timed_out"] is True

    def test_invalid_sandbox_id_rejected(self, client):
        with patch("main.subprocess.run") as run:
            response = client.post(
                "/sandboxes/--evil/exec", json={"argv": ["/bin/true"]}, headers=AUTH
            )
        assert response.status_code == 422
        run.assert_not_called()


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
