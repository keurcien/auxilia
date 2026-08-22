import pytest
from pydantic import ValidationError

from app.sandbox.models import SandboxProviderType
from app.sandbox.schemas import config_extras, validate_config


def test_opensandbox_defaults_materialize_and_secret_is_optional():
    validated = validate_config(
        SandboxProviderType.opensandbox,
        url="sandbox.example.com",
        secret=None,
        config={},
    )
    extras = config_extras(validated)
    assert extras == {
        "default_packages": [],
        "timeout": 1800,
        "default_image": "python:3.12-slim",
        "volume_mounts": [],
        "use_server_proxy": True,
    }


def test_config_extras_never_contains_column_fields():
    validated = validate_config(
        SandboxProviderType.opensandbox,
        url="sandbox.example.com",
        secret="sk-secret",
        config={"default_image": "python:3.13"},
    )
    extras = config_extras(validated)
    assert "url" not in extras
    assert "secret" not in extras
    assert "provider" not in extras
    assert extras["default_image"] == "python:3.13"


def test_cloudrun_requires_a_gateway_secret():
    with pytest.raises(ValidationError, match="gateway secret"):
        validate_config(
            SandboxProviderType.cloudrun,
            url="https://gateway.run.app",
            secret=None,
            config={},
        )


def test_cloudrun_with_secret_validates():
    validated = validate_config(
        SandboxProviderType.cloudrun,
        url="https://gateway.run.app",
        secret="shared-secret",
        config={"allow_egress": True},
    )
    extras = config_extras(validated)
    assert extras["allow_egress"] is True
    assert extras["snapshot_prefix"] == "sandbox-snapshots/"
    assert extras["gcs_bucket"] is None


def test_daytona_requires_an_api_key():
    with pytest.raises(ValidationError, match="API key"):
        validate_config(
            SandboxProviderType.daytona,
            url="https://app.daytona.io/api",
            secret=None,
            config={},
        )


def test_daytona_defaults():
    validated = validate_config(
        SandboxProviderType.daytona,
        url="https://app.daytona.io/api",
        secret="dtn_key",
        config={},
    )
    extras = config_extras(validated)
    assert extras["target"] == "us"
    assert extras["snapshot"] is None
    assert extras["auto_stop_interval"] == 15


def test_wrong_provider_extras_are_rejected():
    # Extra keys that belong to another provider must not silently persist.
    with pytest.raises(ValidationError):
        validate_config(
            SandboxProviderType.opensandbox,
            url="sandbox.example.com",
            secret=None,
            config={"gcs_bucket": "not-an-opensandbox-field"},
        )
