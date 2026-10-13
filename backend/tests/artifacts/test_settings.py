import pytest
from pydantic import ValidationError

from app.artifacts.settings import ArtifactSettings


@pytest.mark.parametrize(
    "sources",
    [
        ["https:"],
        [],
        ["https://cdn.jsdelivr.net", "https://*.example.com:8443/libs/"],
    ],
)
def test_html_sources_accept_https_csp_sources(sources):
    assert (
        ArtifactSettings(_env_file=None, html_sources=sources).html_sources == sources
    )


@pytest.mark.parametrize(
    "source",
    [
        "http://cdn.example.com",
        "*",
        "'unsafe-eval'",
        "https://cdn.example.com; connect-src *",
        "https://cdn.example.com https://other.example.com",
        "https://cdn.example.com:65536",
        "https://cdn.example.com:0",
    ],
)
def test_html_sources_reject_anything_that_could_widen_the_policy(source):
    with pytest.raises(ValidationError):
        ArtifactSettings(_env_file=None, html_sources=[source])


def test_html_sources_read_json_from_env(monkeypatch):
    monkeypatch.setenv("ARTIFACT_HTML_SOURCES", '["https://cdnjs.cloudflare.com"]')
    assert ArtifactSettings(_env_file=None).html_sources == [
        "https://cdnjs.cloudflare.com"
    ]
