"""A repository on a code host, fetched over its REST API — no git binary.

Every host has the same two calls: resolve a ref to a commit SHA, download an
archive of that commit. Subclasses provide the two URLs and the auth header;
this class does the HTTP, the bounds and the error mapping.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from skillkit.errors import (
    AuthenticationError,
    LimitExceeded,
    RevisionNotFound,
    SourceUnavailable,
)
from skillkit.model import Limits, ResolvedSource
from skillkit.sources.archive import ArchiveSource
from skillkit.sources.base import CredentialsProvider


DEFAULT_TIMEOUT = 30.0


class HostedSource:
    kind = "hosted"

    def __init__(
        self,
        url: str,
        *,
        ref: str = "main",
        subpath: str | None = None,
        credentials: CredentialsProvider | None = None,
        full_depth: bool = False,
        limits: Limits = Limits(),
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/").removesuffix(".git")
        self.ref = ref
        self.subpath = subpath
        self.credentials = credentials
        self.full_depth = full_depth
        self.limits = limits
        self._client = client
        parts = urlsplit(self.url)
        if not parts.scheme or not parts.netloc or parts.path.count("/") < 2:
            raise ValueError(f"not a repository URL: {url}")
        self.host = parts.netloc
        self.api_base = f"{parts.scheme}://{parts.netloc}"
        self.project_path = parts.path.strip("/")

    # -- what a host adapter provides ----------------------------------------

    def commit_url(self, ref: str) -> str:
        raise NotImplementedError

    def archive_url(self, sha: str) -> str:
        raise NotImplementedError

    def auth_headers(self, token: str) -> dict[str, str]:
        raise NotImplementedError

    def sha_from(self, payload: dict) -> str:
        return str(payload["sha"])

    # -- the shared shape ------------------------------------------------------

    def resolve(self) -> ResolvedSource:
        sha = self.resolve_revision()
        data = self.download(sha)
        return ArchiveSource(
            data,
            filename="archive.tar.gz",
            url=self.url,
            ref=self.ref,
            revision=sha,
            kind=self.kind,
            subpath=self.subpath,
            full_depth=self.full_depth,
            limits=self.limits,
        ).resolve()

    def resolve_revision(self) -> str:
        response = self._get(self.commit_url(self.ref))
        try:
            return self.sha_from(response.json())
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(f"{self.host}: unexpected commit payload") from exc

    def download(self, sha: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        with self._stream(self.archive_url(sha)) as response:
            self._raise_for(response)
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self.limits.max_download_bytes:
                    raise LimitExceeded(
                        f"archive is over {self.limits.max_download_bytes} bytes"
                    )
                chunks.append(chunk)
        return b"".join(chunks)

    def _headers(self) -> dict[str, str]:
        # A branch ref is resolved on every sync; ask the host's edge not to
        # serve a cached answer (GitHub caches `commits/{branch}` briefly).
        headers = {
            "Accept": "application/json",
            "User-Agent": "skillkit",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        token = self.credentials.token(self.host) if self.credentials else None
        if token:
            headers.update(self.auth_headers(token))
        return headers

    def _client_or_new(self) -> httpx.Client:
        return self._client or httpx.Client(
            timeout=DEFAULT_TIMEOUT, follow_redirects=True
        )

    def _get(self, url: str) -> httpx.Response:
        client = self._client_or_new()
        try:
            response = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"{self.host}: {exc.__class__.__name__}") from exc
        finally:
            if client is not self._client:
                client.close()
        self._raise_for(response)
        return response

    def _stream(self, url: str):
        client = self._client_or_new()
        try:
            return client.stream("GET", url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"{self.host}: {exc.__class__.__name__}") from exc

    def _raise_for(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise AuthenticationError(
                f"{self.host} refused the request ({status}); check the token and its scopes"
            )
        if status == 404:
            raise RevisionNotFound(
                f"{self.project_path}@{self.ref}: repository, ref or path not found on {self.host}"
            )
        if status == 429 or status >= 500:
            raise SourceUnavailable(f"{self.host} answered {status}")
        if status >= 400:
            raise SourceUnavailable(f"{self.host} answered {status}")
