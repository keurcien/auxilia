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
import subprocess
import tempfile
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

app = FastAPI(title="auxilia sandbox gateway", docs_url=None, redoc_url=None)


def verify_secret(authorization: str | None = Header(default=None)) -> None:
    if not SECRET:
        raise HTTPException(status_code=503, detail="Gateway secret not configured")
    if authorization != f"Bearer {SECRET}":
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


def _launch(sandbox_id: str, *, allow_egress: bool, import_tar: bytes | None) -> None:
    # `sandbox run <id>` with no command starts an empty persistent sandbox.
    cmd = [CLI, "run", sandbox_id, "--detach", "--write"]
    if allow_egress and ALLOW_EGRESS:
        cmd.append("--allow-egress")

    def run_launch(extra: list[str]) -> None:
        result = subprocess.run(
            [*cmd, *extra],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
        )
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


@app.post("/sandboxes/{sandbox_id}/exec", dependencies=[Depends(verify_secret)])
def exec_in_sandbox(
    request: ExecRequest, sandbox_id: str = Depends(valid_sandbox_id)
) -> ExecResponse:
    try:
        result = subprocess.run(
            [CLI, "exec", sandbox_id, "--", *request.argv],
            capture_output=True,
            timeout=request.timeout,
        )
    except subprocess.TimeoutExpired:
        return ExecResponse(
            stdout_b64="", stderr_b64="", exit_code=None, timed_out=True
        )
    return ExecResponse(
        stdout_b64=base64.b64encode(result.stdout).decode("ascii"),
        stderr_b64=base64.b64encode(result.stderr).decode("ascii"),
        exit_code=result.returncode,
    )


@app.get("/sandboxes/{sandbox_id}/tar", dependencies=[Depends(verify_secret)])
def export_sandbox_tar(sandbox_id: str = Depends(valid_sandbox_id)) -> Response:
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        result = subprocess.run(
            [CLI, "tar", sandbox_id, f"--file={tmp.name}"],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
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
    subprocess.run(
        [CLI, "delete", sandbox_id, "--force"],
        capture_output=True,
        timeout=_CLI_TIMEOUT,
    )
    return Response(status_code=204)
