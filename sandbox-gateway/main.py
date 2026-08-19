"""auxilia sandbox gateway: the Cloud Run `sandbox` CLI over HTTP.

A minimal, self-contained Cloud Run service. Deploy it with
`--sandbox-launcher` so the platform mounts the sandbox CLI, then point the
auxilia backend at it via CLOUD_RUN_SANDBOX_GATEWAY_URL — the backend's
GatewayTransport (backend/app/sandbox/transport.py) is the only client and
defines the HTTP contract mirrored here.

Sandboxed code sees THIS container's filesystem read-only, so the libraries
installed in the Dockerfile are the sandbox runtime environment for agents.

Every request must carry the shared secret (CLOUD_RUN_SANDBOX_GATEWAY_SECRET)
as a bearer token; the service refuses all traffic when the secret is unset.

Endpoints are sync `def` on purpose — CLI calls block for up to the exec
timeout, so FastAPI must run them on its threadpool, not the event loop.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import signal
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

CLI = "/usr/local/gcp/bin/sandbox"

SECRET = os.environ.get("CLOUD_RUN_SANDBOX_GATEWAY_SECRET")

# Sandboxes get outbound network access iff the gateway is deployed with
# ALLOW_EGRESS=true. Kept gateway-side: the operator who owns this service
# decides its egress posture, not the calling backend.
ALLOW_EGRESS = os.environ.get("ALLOW_EGRESS", "").lower() == "true"

_SANDBOX_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"

# CLI lifecycle operations (run/tar/delete) are control-plane calls, not
# user code — fixed generous timeout.
_CLI_TIMEOUT = 120

# Gateway-side cap on a single exec; the client enforces its own (smaller)
# command timeout and treats `timed_out` as exit code 124.
MAX_EXEC_TIMEOUT = 60 * 60

# Per-stream cap on captured exec output; anything past it is drained and
# discarded so a runaway command (`yes`) can't exhaust gateway memory.
MAX_STREAM_BYTES = 2 * 1024 * 1024
_TRUNCATION_NOTICE = b"\n[output truncated by gateway]\n"

# How long to wait for the pipe readers after the CLI is gone. A descendant
# that escaped the process group can hold the pipe open forever; past this
# grace the request answers with what was captured instead of hanging.
_READER_GRACE_SECONDS = 10.0

app = FastAPI(title="auxilia sandbox gateway", docs_url=None, redoc_url=None)


def verify_secret(authorization: str | None = Header(default=None)) -> None:
    if not SECRET:
        raise HTTPException(status_code=503, detail="Gateway secret not configured")
    expected = f"Bearer {SECRET}".encode()
    if not secrets.compare_digest((authorization or "").encode(), expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


def valid_sandbox_id(sandbox_id: str) -> str:
    if not re.match(_SANDBOX_ID_PATTERN, sandbox_id) or len(sandbox_id) > 64:
        raise HTTPException(status_code=422, detail="Invalid sandbox id")
    return sandbox_id


class LaunchRequest(BaseModel):
    sandbox_id: str = Field(pattern=_SANDBOX_ID_PATTERN, max_length=64)
    allow_egress: bool = False


class ExecRequest(BaseModel):
    argv: list[str] = Field(min_length=1)
    timeout: int = Field(default=30 * 60, ge=1, le=MAX_EXEC_TIMEOUT)


class ExecResponse(BaseModel):
    stdout_b64: str
    stderr_b64: str
    exit_code: int | None
    timed_out: bool = False
    truncated: bool = False


def _run_cli(argv: list[str], *, describe: str) -> subprocess.CompletedProcess:
    """Run a control-plane CLI call; a stalled CLI maps to 504, not a bare 500."""
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"{describe} timed out after {_CLI_TIMEOUT}s",
        ) from None


def _launch(sandbox_id: str, *, allow_egress: bool, import_tar: bytes | None) -> None:
    # `sandbox run <id>` with no command starts an empty persistent sandbox.
    cmd = [CLI, "run", sandbox_id, "--detach", "--write"]
    if allow_egress and ALLOW_EGRESS:
        cmd.append("--allow-egress")

    def run_launch(extra: list[str]) -> None:
        result = _run_cli([*cmd, *extra], describe=f"sandbox launch for {sandbox_id}")
        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to launch sandbox {sandbox_id}: "
                f"{result.stderr or result.stdout}",
            )

    if import_tar is not None:
        with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
            tmp.write(import_tar)
            tmp.flush()
            run_launch([f"--import-tar={tmp.name}"])
    else:
        run_launch([])


# NOT /healthz: Google's frontend reserves that path on run.app domains and
# answers it with its own 404 before the request reaches the container.
@app.get("/health")
def health() -> dict:
    return {"cli_mounted": Path(CLI).exists(), "allow_egress": ALLOW_EGRESS}


@app.post("/sandboxes", status_code=201, dependencies=[Depends(verify_secret)])
def launch_sandbox(request: LaunchRequest) -> dict:
    _launch(request.sandbox_id, allow_egress=request.allow_egress, import_tar=None)
    return {"sandbox_id": request.sandbox_id}


@app.post(
    "/sandboxes/{sandbox_id}/restore",
    status_code=201,
    dependencies=[Depends(verify_secret)],
)
async def restore_sandbox(
    request: Request,
    allow_egress: bool = False,
    sandbox_id: str = Depends(valid_sandbox_id),
) -> dict:
    """Launch a sandbox seeded with a snapshot tar (raw request body).

    Binary body instead of base64 JSON: Cloud Run caps HTTP/1 requests at
    32MiB, and base64 would burn a third of that on encoding overhead.
    """
    tar_bytes = await request.body()
    if not tar_bytes:
        raise HTTPException(status_code=422, detail="Empty snapshot body")
    await run_in_threadpool(
        _launch, sandbox_id, allow_egress=allow_egress, import_tar=tar_bytes
    )
    return {"sandbox_id": sandbox_id}


def _read_capped(stream, cap: int) -> tuple[bytes, bool]:
    """Read a pipe to EOF, keeping at most `cap` bytes and discarding the rest —
    the pipe must be drained even past the cap or the child blocks on write."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while chunk := stream.read(65536):
        if total < cap:
            keep = chunk[: cap - total]
            chunks.append(keep)
            total += len(keep)
            truncated = truncated or len(keep) < len(chunk)
        else:
            truncated = True
    return b"".join(chunks), truncated


def _kill_tree(proc) -> None:
    """SIGKILL the CLI's whole process group — a child left holding the output
    pipes would otherwise keep the readers (and the request) blocked forever."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        proc.kill()
    proc.wait()


@app.post("/sandboxes/{sandbox_id}/exec", dependencies=[Depends(verify_secret)])
def exec_in_sandbox(
    request: ExecRequest, sandbox_id: str = Depends(valid_sandbox_id)
) -> ExecResponse:
    proc = subprocess.Popen(
        [CLI, "exec", sandbox_id, "--", *request.argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    captured: dict[str, tuple[bytes, bool]] = {}
    readers = [
        threading.Thread(
            target=lambda n=name, s=stream: captured.__setitem__(
                n, _read_capped(s, MAX_STREAM_BYTES)
            ),
            daemon=True,
        )
        for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))
    ]
    for reader in readers:
        reader.start()
    try:
        proc.wait(timeout=request.timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        timed_out = True
    # Bounded join: killing the group EOFs the pipes in every normal case; a
    # descendant that escaped the group is abandoned (daemon reader) past the
    # grace and the missing stream reports as truncated.
    for reader in readers:
        reader.join(timeout=_READER_GRACE_SECONDS)
    if timed_out:
        return ExecResponse(
            stdout_b64="", stderr_b64="", exit_code=None, timed_out=True
        )
    stdout, stdout_truncated = captured.get("stdout", (b"", True))
    stderr, stderr_truncated = captured.get("stderr", (b"", True))
    if stdout_truncated:
        stdout += _TRUNCATION_NOTICE
    if stderr_truncated:
        stderr += _TRUNCATION_NOTICE
    return ExecResponse(
        stdout_b64=base64.b64encode(stdout).decode("ascii"),
        stderr_b64=base64.b64encode(stderr).decode("ascii"),
        exit_code=proc.returncode,
        truncated=stdout_truncated or stderr_truncated,
    )


@app.get("/sandboxes/{sandbox_id}/tar", dependencies=[Depends(verify_secret)])
def export_sandbox_tar(sandbox_id: str = Depends(valid_sandbox_id)) -> Response:
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        result = _run_cli(
            [CLI, "tar", sandbox_id, f"--file={tmp.name}"],
            describe=f"sandbox tar for {sandbox_id}",
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail=f"sandbox tar failed for {sandbox_id}: {result.stderr}",
            )
        tar_bytes = Path(tmp.name).read_bytes()
    return Response(content=tar_bytes, media_type="application/x-tar")


@app.delete(
    "/sandboxes/{sandbox_id}", status_code=204, dependencies=[Depends(verify_secret)]
)
def delete_sandbox(sandbox_id: str = Depends(valid_sandbox_id)) -> Response:
    result = _run_cli(
        [CLI, "delete", sandbox_id, "--force"],
        describe=f"sandbox delete for {sandbox_id}",
    )
    if result.returncode != 0:
        # Idempotent: deleting a sandbox that's already gone is a success.
        error = (result.stderr or result.stdout or "").lower()
        if not any(m in error for m in ("not found", "no such", "does not exist")):
            raise HTTPException(
                status_code=502,
                detail=f"sandbox delete failed for {sandbox_id}: "
                f"{result.stderr or result.stdout}",
            )
    return Response(status_code=204)
