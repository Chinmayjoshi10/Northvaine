"""The HTTP side of resuming a run (D144, jobs/resume.py): a transport that serves a saved answer
for a request seen before and saves new good answers. Requests are kept only as a hash, so an API
key in a request never leaves the process; 5xx and 429 answers are never saved."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import httpx

KEPT_HEADERS = ("content-type", "retry-after", "location")


def request_hash(*parts: bytes | str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8") if isinstance(part, str) else part)
        digest.update(b"\x00")
    return digest.hexdigest()


def caching_client(cache: Any, timeout: float = 60.0) -> httpx.AsyncClient:
    """An AsyncClient whose answers go through `cache` (jobs.resume.ResumeCache)."""
    return httpx.AsyncClient(
        timeout=timeout, transport=CachingTransport(httpx.AsyncHTTPTransport(), cache)
    )


class CachingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, cache: Any) -> None:
        self.inner = inner
        self.cache = cache

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        key = "http:" + request_hash(request.method, str(request.url), request.content)
        saved = self.cache.get(key)
        if saved is not None:
            data = json.loads(saved)
            return httpx.Response(
                data["status"],
                headers=data["headers"],
                content=base64.b64decode(data["body"]),
                request=request,
            )
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        if response.status_code < 500 and response.status_code != 429:
            headers = {k: response.headers[k] for k in KEPT_HEADERS if k in response.headers}
            self.cache.keep(
                key,
                json.dumps(
                    {
                        "status": response.status_code,
                        "headers": headers,
                        "body": base64.b64encode(body).decode("ascii"),
                    }
                ),
            )
        # `aread` has already undone any compression: the body passed on is plain, so the headers
        # that describe the wire form (encoding, length) must not travel with it
        plain = [
            (k, v)
            for k, v in response.headers.multi_items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        ]
        return httpx.Response(response.status_code, headers=plain, content=body, request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()
