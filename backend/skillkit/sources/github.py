"""GitHub (github.com or GitHub Enterprise) over the REST API."""

from __future__ import annotations

from skillkit.sources.hosted import HostedSource


class GitHubSource(HostedSource):
    kind = "github"

    def _api(self) -> str:
        if self.host == "github.com":
            return "https://api.github.com"
        return f"{self.api_base}/api/v3"

    def commit_url(self, ref: str) -> str:
        return f"{self._api()}/repos/{self.project_path}/commits/{ref}"

    def archive_url(self, sha: str) -> str:
        return f"{self._api()}/repos/{self.project_path}/tarball/{sha}"

    def auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
