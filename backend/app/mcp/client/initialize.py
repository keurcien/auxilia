"""Runtime patches to ``mcp.ClientSession`` for MCP Apps interoperability.

The bundled MCP Python SDK doesn't expose two things we need to render
interactive MCP Apps (e.g. Metabase's ``visualize_query`` chart):

1. **UI capability negotiation.** Servers gate UI-bearing tools behind the
   client capability ``io.modelcontextprotocol/ui`` advertised during
   ``initialize``. ``ClientSession.initialize`` hardcodes the capability set
   (``experimental=None``) and offers no hook to add it.
2. **Lenient output validation.** ``ClientSession.call_tool`` validates a
   result's ``structuredContent`` against the tool's ``outputSchema`` and
   *raises* ``RuntimeError`` on mismatch. Metabase's declared schema doesn't
   match what it returns, so the call dies before we ever see the result.

``apply_mcp_client_patches()`` is idempotent and applied once at app startup
(see ``app/main.py``). It patches the class, so it covers both the raw
``connect_to_server`` path and the langchain-mcp-adapters path (both use
``ClientSession`` underneath).
"""

from __future__ import annotations

import logging

import mcp.client.session as mcp_session
import mcp.types as types
from mcp.client.session import ClientSession


logger = logging.getLogger(__name__)

# MCP Apps extension identifier and the capability payload a host advertises.
# https://github.com/modelcontextprotocol/ext-apps (spec 2026-01-26).
UI_EXTENSION = "io.modelcontextprotocol/ui"
UI_CAPABILITY = {"mimeTypes": ["text/html;profile=mcp-app"]}

_PATCHED = False


async def _initialize_with_ui_capability(self: ClientSession) -> types.InitializeResult:
    """Drop-in for ``ClientSession.initialize`` that advertises MCP Apps support.

    Mirrors the upstream method but injects the ``io.modelcontextprotocol/ui``
    capability. We advertise it under both ``extensions`` (where the MCP Apps
    spec puts it) and ``experimental`` (belt-and-suspenders for servers reading
    the older location). ``ClientCapabilities`` allows extra fields, so the
    ``extensions`` key serializes onto the wire.

    Defensive: if the upstream shape drifts, fall back to the original
    ``initialize`` so startup never breaks — we just lose UI tools and log it.
    """
    sampling = (
        (self._sampling_capabilities or types.SamplingCapability())
        if self._sampling_callback is not mcp_session._default_sampling_callback
        else None
    )
    elicitation = (
        types.ElicitationCapability(
            form=types.FormElicitationCapability(),
            url=types.UrlElicitationCapability(),
        )
        if self._elicitation_callback is not mcp_session._default_elicitation_callback
        else None
    )
    roots = (
        types.RootsCapability(listChanged=True)
        if self._list_roots_callback is not mcp_session._default_list_roots_callback
        else None
    )

    capabilities = types.ClientCapabilities(
        sampling=sampling,
        elicitation=elicitation,
        experimental={UI_EXTENSION: UI_CAPABILITY},
        roots=roots,
        tasks=self._task_handlers.build_capability(),
        extensions={UI_EXTENSION: UI_CAPABILITY},
    )

    result = await self.send_request(
        types.ClientRequest(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocolVersion=types.LATEST_PROTOCOL_VERSION,
                    capabilities=capabilities,
                    clientInfo=self._client_info,
                ),
            )
        ),
        types.InitializeResult,
    )

    if result.protocolVersion not in mcp_session.SUPPORTED_PROTOCOL_VERSIONS:
        raise RuntimeError(
            f"Unsupported protocol version from the server: {result.protocolVersion}"
        )

    self._server_capabilities = result.capabilities
    await self.send_notification(
        types.ClientNotification(types.InitializedNotification())
    )
    return result


def _make_lenient_validate(original):
    async def _lenient_validate_tool_result(
        self: ClientSession, name: str, result: types.CallToolResult
    ) -> None:
        """Log output-schema mismatches instead of raising.

        Some servers (e.g. Metabase) return ``structuredContent`` that doesn't
        match their declared ``outputSchema``. Upstream raises ``RuntimeError``,
        which kills the tool call; we'd rather hand the result to the model.
        """
        try:
            await original(self, name, result)
        except Exception as exc:  # noqa: BLE001 - intentionally lenient
            logger.warning(
                "Ignoring MCP output validation error for tool %s: %s", name, exc
            )

    return _lenient_validate_tool_result


def apply_mcp_client_patches() -> None:
    """Patch ``ClientSession`` for MCP Apps. Idempotent; call once at startup."""
    global _PATCHED
    if _PATCHED:
        return
    ClientSession.initialize = _initialize_with_ui_capability
    ClientSession._validate_tool_result = _make_lenient_validate(
        ClientSession._validate_tool_result
    )
    _PATCHED = True
    logger.info("Applied MCP client patches (UI capability + lenient validation)")
