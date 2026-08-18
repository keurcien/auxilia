# auxilia sandbox gateway

A minimal Cloud Run service that exposes [Cloud Run sandboxes](https://docs.cloud.google.com/run/docs/code-execution) (public preview) over HTTP, so the auxilia backend — running anywhere, including a laptop — can execute agent code in isolated sandboxes.

The backend's `GatewayTransport` (`backend/app/sandbox/cloudrun/transport.py`) is the only client, and this gateway is the **only** deployment that runs the sandbox CLI — the backend never drives it directly, so backend and worker services need no `--sandbox-launcher` and no sandbox resource headroom.

**The Docker image is the sandbox runtime environment**: sandboxed code sees this container's filesystem read-only. Edit the second `pip install` block in the `Dockerfile` to change which libraries agent code can import.

## Deploy

```sh
gcloud beta run deploy sandbox-gateway \
  --source . \
  --region <region> \
  --sandbox-launcher \
  --no-allow-unauthenticated=false \
  --set-env-vars CLOUD_RUN_SANDBOX_GATEWAY_SECRET=$(openssl rand -hex 32)
```

Notes:

- `--sandbox-launcher` (gen2) is required — it mounts the `sandbox` CLI at `/usr/local/gcp/bin/sandbox`. Check `GET /health` → `cli_mounted: true` after deploying.
- The service is public at the Cloud Run layer and protected by the bearer secret; it fails closed (503) if the secret is unset.
- Set `ALLOW_EGRESS=true` on the service to let sandboxes get outbound network access (needed for in-sandbox `pip install`). Off by default.
- Stateful sandboxes live inside one instance. Either run with `--max-instances 1` and session affinity, or rely on the backend's GCS snapshot restore (`CLOUD_RUN_SANDBOX_GCS_BUCKET`) for cross-instance continuity.

## Point the backend at it

```env
SANDBOX_PROVIDER=cloudrun
CLOUD_RUN_SANDBOX_GATEWAY_URL=https://sandbox-gateway-....run.app
CLOUD_RUN_SANDBOX_GATEWAY_SECRET=<same secret>
```

## API

All endpoints except `/health` require `Authorization: Bearer <secret>`.

| Endpoint | Purpose |
| --- | --- |
| `POST /sandboxes` | Launch a detached named sandbox (`{sandbox_id, allow_egress, import_tar_b64?}`) |
| `POST /sandboxes/{id}/exec` | Run argv in the sandbox → `{stdout_b64, stderr_b64, exit_code, timed_out}` |
| `GET /sandboxes/{id}/tar` | Export the writable overlay as a tar (binary) |
| `DELETE /sandboxes/{id}` | Delete the sandbox |
| `GET /health` | `{cli_mounted, allow_egress}` |

## Tests

```sh
pip install fastapi httpx pytest && pytest
```
