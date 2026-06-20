"""Tests for the ClientSession MCP Apps patches (app/mcp/client/initialize.py).

Focus on the documented defensive fallback: the patch replaces
``ClientSession.initialize`` for *every* MCP connection, so if the SDK's private
internals drift and we can't assemble our UI-capability request, it must fall
back to the original ``initialize`` rather than break all connections.
"""

from __future__ import annotations

import pytest
from mcp.client.session import ClientSession

import app.mcp.client.initialize as initialize


async def test_initialize_falls_back_to_original_on_sdk_drift(monkeypatch):
    """Capability assembly raising (simulated SDK drift) → fall back to original."""

    def _drift(_self):
        raise AttributeError("ClientSession._sampling_callback renamed upstream")

    monkeypatch.setattr(initialize, "_build_ui_capabilities", _drift)

    calls = []

    async def _fake_original(self):
        calls.append(self)
        return "ORIGINAL_RESULT"

    monkeypatch.setattr(initialize, "_original_initialize", _fake_original)

    sentinel_self = object()
    result = await initialize._initialize_with_ui_capability(sentinel_self)

    assert result == "ORIGINAL_RESULT"
    assert calls == [sentinel_self]


async def test_initialize_reraises_when_no_original_captured(monkeypatch):
    """If patches weren't applied (no original captured), the drift error propagates
    instead of being silently swallowed."""

    def _drift(_self):
        raise AttributeError("drift")

    monkeypatch.setattr(initialize, "_build_ui_capabilities", _drift)
    monkeypatch.setattr(initialize, "_original_initialize", None)

    with pytest.raises(AttributeError):
        await initialize._initialize_with_ui_capability(object())


def test_apply_captures_original_before_overwriting(monkeypatch):
    """apply_mcp_client_patches must capture the original initialize *before*
    replacing it, otherwise there is nothing to fall back to."""

    sentinel_initialize = object()
    monkeypatch.setattr(ClientSession, "initialize", sentinel_initialize, raising=False)
    # Stub so apply's lenient-validation wrap targets a throwaway monkeypatch
    # restores, not the real method.
    monkeypatch.setattr(
        ClientSession, "_validate_tool_result", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(initialize, "_PATCHED", False)
    monkeypatch.setattr(initialize, "_original_initialize", None)

    initialize.apply_mcp_client_patches()

    assert initialize._original_initialize is sentinel_initialize
    assert ClientSession.initialize is initialize._initialize_with_ui_capability
