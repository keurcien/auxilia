"""GitLab (gitlab.com or any instance) over the REST API v4."""

from __future__ import annotations

from urllib.parse import quote

from skillkit.sources.hosted import HostedSource


class GitLabSource(HostedSource):
    kind = "gitlab"

    def _project(self) -> str:
        return quote(self.project_path, safe="")

    def commit_url(self, ref: str) -> str:
        return f"{self.api_base}/api/v4/projects/{self._project()}/repository/commits/{quote(ref, safe='')}"

    def archive_url(self, sha: str) -> str:
        return f"{self.api_base}/api/v4/projects/{self._project()}/repository/archive.tar.gz?sha={sha}"

    def auth_headers(self, token: str) -> dict[str, str]:
        return {"PRIVATE-TOKEN": token}

    def sha_from(self, payload: dict) -> str:
        return str(payload["id"])
