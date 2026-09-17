"""GitHub / GitLab adapters against a stub transport — never the network."""

import httpx
import pytest

from skillkit import (
    AuthenticationError,
    GitHubSource,
    GitLabSource,
    RevisionNotFound,
    SourceUnavailable,
    StaticCredentials,
)
from tests.skillkit.conftest import tar_bytes


def transport(tree, *, commit_status=200, archive_status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if "/commits/" in request.url.path:
            if commit_status != 200:
                return httpx.Response(commit_status, json={"message": "nope"})
            return httpx.Response(200, json={"sha": "9f2c1ab3e5", "id": "9f2c1ab3e5"})
        if archive_status != 200:
            return httpx.Response(archive_status)
        return httpx.Response(200, content=tar_bytes(tree))

    return httpx.MockTransport(handler)


def test_github_resolves_ref_then_downloads_the_tarball(repo_tree):
    seen = []
    client = httpx.Client(transport=transport(repo_tree, seen=seen))
    source = GitHubSource(
        "https://github.com/acme/skills.git",
        ref="v1.4.0",
        credentials=StaticCredentials("tok"),
        client=client,
    )
    resolved = source.resolve()
    assert (
        resolved.kind == "github"
        and resolved.revision == "9f2c1ab3e5"
        and resolved.ref == "v1.4.0"
    )
    assert resolved.url == "https://github.com/acme/skills"
    assert [str(r.url) for r in seen] == [
        "https://api.github.com/repos/acme/skills/commits/v1.4.0",
        "https://api.github.com/repos/acme/skills/tarball/9f2c1ab3e5",
    ]
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert {s.name for s in resolved.skills} >= {"weekly-brief", "margin-audit"}


def test_github_enterprise_uses_the_instance_api(repo_tree):
    seen = []
    source = GitHubSource(
        "https://ghe.acme.io/team/skills",
        client=httpx.Client(transport=transport(repo_tree, seen=seen)),
    )
    source.resolve()
    assert str(seen[0].url).startswith(
        "https://ghe.acme.io/api/v3/repos/team/skills/commits/main"
    )


def test_gitlab_encodes_the_project_and_uses_private_token(repo_tree):
    seen = []
    source = GitLabSource(
        "https://gitlab.acme.io/group/sub/skills",
        ref="main",
        credentials=StaticCredentials("glpat"),
        client=httpx.Client(transport=transport(repo_tree, seen=seen)),
    )
    resolved = source.resolve()
    assert resolved.kind == "gitlab" and resolved.revision == "9f2c1ab3e5"
    assert (
        str(seen[0].url)
        == "https://gitlab.acme.io/api/v4/projects/group%2Fsub%2Fskills/repository/commits/main"
    )
    assert str(seen[1].url).endswith("/repository/archive.tar.gz?sha=9f2c1ab3e5")
    assert seen[0].headers["PRIVATE-TOKEN"] == "glpat"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, RevisionNotFound),
        (500, SourceUnavailable),
        (429, SourceUnavailable),
    ],
)
def test_errors_are_distinct_types(repo_tree, status, error):
    source = GitHubSource(
        "https://github.com/acme/skills",
        client=httpx.Client(transport=transport(repo_tree, commit_status=status)),
    )
    with pytest.raises(error):
        source.resolve()


def test_network_failure_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    source = GitHubSource(
        "https://github.com/acme/skills",
        client=httpx.Client(transport=httpx.MockTransport(boom)),
    )
    with pytest.raises(SourceUnavailable):
        source.resolve()


def test_not_a_repository_url():
    with pytest.raises(ValueError):
        GitHubSource("https://github.com/acme")
