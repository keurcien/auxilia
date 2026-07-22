"""Unit tests for the sandbox settings facade."""

import pytest

from app.sandbox.settings import sandbox_settings


@pytest.fixture
def cloudrun_provider(monkeypatch):
    monkeypatch.setattr(sandbox_settings, "provider", "cloudrun")


def test_cloudrun_enabled_requires_url_and_secret(cloudrun_provider, monkeypatch):
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_url", "http://gw.test")
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_secret", "s3cret")
    assert sandbox_settings.enabled is True


def test_cloudrun_disabled_without_secret(cloudrun_provider, monkeypatch):
    """The gateway fails closed without the secret — advertising the feature
    would enable tools that can never work."""
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_url", "http://gw.test")
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_secret", None)
    assert sandbox_settings.enabled is False


def test_cloudrun_disabled_without_url(cloudrun_provider, monkeypatch):
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_url", None)
    monkeypatch.setattr(sandbox_settings.cloudrun, "gateway_secret", "s3cret")
    assert sandbox_settings.enabled is False


def test_opensandbox_enabled_follows_domain(monkeypatch):
    monkeypatch.setattr(sandbox_settings, "provider", "opensandbox")
    monkeypatch.setattr(sandbox_settings.opensandbox, "domain", "sandbox.test")
    assert sandbox_settings.enabled is True
    monkeypatch.setattr(sandbox_settings.opensandbox, "domain", None)
    assert sandbox_settings.enabled is False
