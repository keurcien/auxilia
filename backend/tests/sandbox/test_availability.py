"""Sandbox availability is a typed, pre-run failure — never something the
model gets to see."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions import SandboxUnavailableError, status_for
from app.sandbox.provider import (
    BaseSandboxProvider,
    SandboxGoneError,
    ensure_sandboxes_available,
    open_sandbox,
)
from tests.sandbox.stub_sandbox import StubSandbox


class _Provider(BaseSandboxProvider):
    """A provider whose probe/create/connect behaviour is scripted."""

    def __init__(self, *, probe=None, create=None, connect=None):
        super().__init__(MagicMock(), sandbox_id="row-1", name="Cloud Run prod")
        self._probe_effect = probe
        self._create_effect = create
        self._connect_effect = connect

    def _probe(self):
        if self._probe_effect:
            raise self._probe_effect

    def _create_backend(self, *, timeout_minutes):
        if self._create_effect:
            raise self._create_effect
        return StubSandbox("sbx-new")

    def _destroy_backend(self, backend):
        pass

    def connect(self, sandbox_id):
        if self._connect_effect:
            raise self._connect_effect
        return StubSandbox(sandbox_id), "ok"


def test_error_is_a_409_with_a_machine_readable_body():
    exc = SandboxUnavailableError("row-1", "Cloud Run prod", "gateway down")
    assert status_for(exc) == 409
    assert exc.body() == {
        "error": "sandbox_unavailable",
        "sandbox_id": "row-1",
        "detail": "Sandbox 'Cloud Run prod' is not available: gateway down",
    }


def test_check_available_wraps_any_probe_failure():
    with pytest.raises(SandboxUnavailableError, match=r"Cloud Run prod.*refused"):
        _Provider(probe=ConnectionError("refused")).check_available()
    _Provider().check_available()  # a healthy probe is silent


def test_open_sandbox_types_a_create_failure():
    """A provider that cannot create is unavailable — the run must fail with
    the same typed error the pre-flight would have raised."""
    with (
        patch("app.sandbox.provider.install_default_packages"),
        pytest.raises(SandboxUnavailableError, match="create failed"),
    ):
        open_sandbox(_Provider(create=ConnectionError("gateway down")), None)


def test_open_sandbox_types_a_reconnect_failure_but_replaces_a_gone_one():
    with pytest.raises(SandboxUnavailableError, match="reconnect failed"):
        open_sandbox(_Provider(connect=ConnectionError("gateway down")), "sbx-old")
    with patch("app.sandbox.provider.install_default_packages"):
        session = open_sandbox(_Provider(connect=SandboxGoneError("gone")), "sbx-old")
    assert session.replaced is True


async def test_ensure_probes_each_distinct_row_once():
    # `name=` is MagicMock's own kwarg, so the attribute is set afterwards.
    row, other = MagicMock(id=uuid4()), MagicMock(id=uuid4())
    row.name, other.name = "A", "B"
    probed = []

    def fake_build(r):
        provider = MagicMock()
        provider.check_available.side_effect = lambda: probed.append(r.name)
        return provider

    with patch("app.sandbox.provider.build_provider", side_effect=fake_build):
        await ensure_sandboxes_available([row, other, row])

    assert probed == ["A", "B"]


async def test_ensure_is_a_no_op_without_sandboxes():
    with patch("app.sandbox.provider.build_provider") as build:
        await ensure_sandboxes_available([])
    build.assert_not_called()


async def test_ensure_types_a_row_that_no_longer_validates():
    row = MagicMock(id=uuid4())
    row.name = "Broken"
    with (
        patch(
            "app.sandbox.provider.build_provider",
            side_effect=ValueError("secret cleared"),
        ),
        pytest.raises(SandboxUnavailableError, match=r"Broken.*invalid configuration"),
    ):
        await ensure_sandboxes_available([row])
