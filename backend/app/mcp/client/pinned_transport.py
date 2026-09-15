"""Optional BigQuery routing workaround; never changes OAuth destinations."""

import logging

import httpx2


BIGQUERY_HOST = "bigquery.googleapis.com"
logger = logging.getLogger(__name__)


class PinnedBigQueryTransport(httpx2.AsyncBaseTransport):
    """Keep HTTP Host and TLS verification tied to Google while pinning TCP.

    httpcore2's sni_hostname extension preserves certificate verification against
    the original hostname. The request is copied so auth, logging and MCP origin
    checks still see the public URL. This is temporary routing, not versioning:
    Google can change the implementation served at an IP at any time.
    """

    def __init__(self, address: str) -> None:
        self.address = address
        self.inner = httpx2.AsyncHTTPTransport(verify=True)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host != BIGQUERY_HOST or request.url.scheme != "https":
            return await self.inner.handle_async_request(request)
        headers = request.headers.copy()
        headers["Host"] = BIGQUERY_HOST
        forwarded = httpx2.Request(
            request.method,
            request.url.copy_with(host=self.address),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": BIGQUERY_HOST},
        )
        response = await self.inner.handle_async_request(forwarded)
        logger.debug(
            "BQ_ROUTE transport=%s destination=%s status=%s",
            id(self),
            self.address,
            response.status_code,
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
