"""Logging setup, with an optional Cloud Logging structured format.

Local development wants plain lines in a terminal. Running on Cloud Run (or
anywhere else shipping stdout to Google Cloud Logging) wants one JSON object
per line in Cloud Logging's structured format instead: `severity` and
`message` land in their own indexed fields rather than being buried in a text
blob. See https://cloud.google.com/logging/docs/structured-logging.

`LOG_FORMAT=gcp` switches to that JSON format; the default, `console`, keeps
plain text and has no GCP dependency — most contributors to this open-source
project are not running on Cloud Run.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.settings import app_settings


_SEVERITY_BY_LEVEL = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# Attributes every `LogRecord` carries. Anything else on the record came from
# `logger.info(..., extra={...})`; those are forwarded as their own top-level
# jsonPayload fields so they're filterable in the Logs Explorer instead of
# being flattened into the message text.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
)


def _uvicorn_http_request(record: logging.LogRecord) -> dict[str, Any] | None:
    """Recover structured request fields from a `uvicorn.access` record.

    `h11_impl.send` logs the access line as
    `access_logger.info('%s - "%s %s HTTP/%s" %d', client_addr, method, path,
    http_version, status)` — no `extra=`, so `record.args` (the raw
    interpolation values) is the only place this data exists; otherwise it's
    only recoverable by re-parsing the formatted message text.

    Note Cloud Run already emits its own, richer `httpRequest` log entry per
    request (latency, request/response size, user agent, referer — none of
    which uvicorn's access log tracks) on `run.googleapis.com/requests`. This
    is only about making *this* line — which exists either way — carry
    `severity`/`httpRequest` fields instead of an opaque text blob, so it's
    filterable the same way.
    """
    if (
        record.name != "uvicorn.access"
        or not isinstance(record.args, tuple)
        or len(record.args) != 5
    ):
        return None
    client_addr, method, path, http_version, status = record.args
    request: dict[str, Any] = {
        "requestMethod": method,
        "requestUrl": path,
        "protocol": f"HTTP/{http_version}",
        "status": status,
    }
    if client_addr:
        # "%s:%d" % (host, port) — rsplit on the last ":" still works for an
        # IPv6 host, which is itself colon-separated. `record.args` elements
        # are typed `object` (logging's `_ArgsType`), hence the `str(...)`.
        request["remoteIp"] = str(client_addr).rsplit(":", 1)[0]
    return request


class GCPJSONFormatter(logging.Formatter):
    """One JSON object per line, in Cloud Logging's structured log format."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            message += "\n" + self.formatStack(record.stack_info)

        entry: dict[str, Any] = {
            "severity": _SEVERITY_BY_LEVEL.get(record.levelno, "DEFAULT"),
            "message": message,
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        if http_request := _uvicorn_http_request(record):
            entry["httpRequest"] = http_request

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in entry:
                entry[key] = value

        return json.dumps(entry, default=str)


def configure_logging() -> None:
    """Attach one handler to the root logger, formatted per `LOG_FORMAT`.

    Previously a handler was only ever attached when `LOG_LEVEL=DEBUG`; at
    INFO (the default) this app's own `logger.info(...)` calls had no handler
    anywhere in the hierarchy and were silently dropped by
    `logging.lastResort`, which only prints WARNING and above. Attaching a
    handler unconditionally fixes that for both formats.

    Idempotent: replaces the root handler list rather than appending, so a
    test re-import or `--reload` doesn't stack duplicate handlers and print
    every line twice.
    """
    if app_settings.log_format == "gcp":
        formatter: logging.Formatter = GCPJSONFormatter()
    else:
        formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(app_settings.log_level.upper())

    # "uvicorn" and "uvicorn.access" install their own handlers with
    # propagate=False (uvicorn.config.LOGGING_CONFIG), applied before this
    # module is even imported — left alone, their plain-text lines would be
    # the only unstructured thing left on stdout in `gcp` format. Reroute them
    # through the root handler instead. ("uvicorn.error" already propagates.)
    for name in ("uvicorn", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    if app_settings.log_level.upper() == "DEBUG":
        # Surface the MCP streamable-HTTP transport so we can see whether a
        # tool call's response is silently dropped (a `202 Accepted` to a
        # request, or an SSE stream that ends without a response) — the two
        # paths behind the BigQuery `execute_sql_readonly` hang. That logger
        # prints JSON-RPC frames only, never the Authorization header, so no
        # bearer token is exposed; `httpx`/`httpcore` are left alone because
        # they can log headers.
        logging.getLogger("mcp.client.streamable_http").setLevel(logging.DEBUG)
        logging.getLogger("app").info(
            "MCP streamable-HTTP transport logging is at DEBUG (LOG_LEVEL=DEBUG); "
            "set LOG_LEVEL=INFO to quiet it once a repro is captured."
        )
