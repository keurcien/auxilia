"""Daytona provider `connect`: wake, reuse, or report the sandbox gone."""

from unittest.mock import MagicMock, patch

import pytest
from daytona.common.errors import DaytonaAuthenticationError, DaytonaNotFoundError

from app.sandbox.daytona.provider import DaytonaProvider
from app.sandbox.provider import SandboxGoneError
from app.sandbox.schemas import DaytonaConfig


def make_provider() -> DaytonaProvider:
    return DaytonaProvider(
        DaytonaConfig(
            url="https://app.daytona.io/api", secret="key", default_packages=[]
        )
    )


def _sandbox(state: str):
    sandbox = MagicMock()
    sandbox.state = MagicMock(value=state)
    sandbox.id = "dtn-1"
    return sandbox


def test_connect_wakes_a_stopped_sandbox():
    client = MagicMock()
    client.get.return_value = _sandbox("stopped")
    with patch.object(DaytonaProvider, "_client", return_value=client):
        _backend, message = make_provider().connect("dtn-1")
    client.start.assert_called_once()
    assert "Restarted" in message


def test_connect_maps_not_found_to_gone():
    client = MagicMock()
    client.get.side_effect = DaytonaNotFoundError("no such sandbox")
    with (
        patch.object(DaytonaProvider, "_client", return_value=client),
        pytest.raises(SandboxGoneError),
    ):
        make_provider().connect("dtn-1")


def test_connect_maps_a_dead_state_to_gone():
    client = MagicMock()
    client.get.return_value = _sandbox("destroyed")
    with (
        patch.object(DaytonaProvider, "_client", return_value=client),
        pytest.raises(SandboxGoneError),
    ):
        make_provider().connect("dtn-1")


def test_connect_propagates_other_errors():
    client = MagicMock()
    client.get.side_effect = DaytonaAuthenticationError("bad key")
    with (
        patch.object(DaytonaProvider, "_client", return_value=client),
        pytest.raises(DaytonaAuthenticationError),
    ):
        make_provider().connect("dtn-1")


def test_probe_pulls_one_page_of_the_listing():
    client = MagicMock()
    client.list.return_value = iter([])
    with patch.object(DaytonaProvider, "_client", return_value=client):
        make_provider().check_available()
    client.list.assert_called_once()


def test_probe_failure_is_typed():
    from app.sandbox.provider import SandboxUnavailableError

    client = MagicMock()
    client.list.side_effect = DaytonaAuthenticationError("bad key")
    with (
        patch.object(DaytonaProvider, "_client", return_value=client),
        pytest.raises(SandboxUnavailableError, match="bad key"),
    ):
        make_provider().check_available()
