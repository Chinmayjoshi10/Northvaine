"""Resume a radar run after a restart (D144).

A run repeats itself: its moment (`as_of`) is fixed when it is queued and its choices are seeded,
so the same inputs give the same requests in the same order. While a run goes, every answer it
receives (sensor HTTP responses, fetched pages, model replies) is saved under the run's key in the
durable store. When the run is started again, saved answers are served at once and only the part
the earlier run never reached goes to the network. A replayed model reply carries zero tokens, so
it costs nothing and is not counted twice against the caps.

Nothing secret is saved: requests are kept only as a hash (an API key in a request never leaves
the process), and only responses that a retry would get again are saved (no 5xx, no 429, no
transport errors, no page fetch errors).
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import AbstractContextManager
from typing import Any

from northvaine.api import durable
from northvaine.brain import llm
from northvaine.brain.replay import _namespace, _plain, _response_dict, exchange_key

logger = logging.getLogger(__name__)


def request_hash(*parts: bytes | str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8") if isinstance(part, str) else part)
        digest.update(b"\x00")
    return digest.hexdigest()


class ResumeCache:
    """Saved answers of one run, keyed by request; loaded once, saved as they arrive."""

    def __init__(self, run_key: str, saved: dict[str, str] | None = None) -> None:
        self.kind = f"cache:{run_key}"
        self.saved: dict[str, str] = dict(saved or {})
        self.hits = 0
        self.misses = 0

    @classmethod
    async def load(cls, run_key: str) -> ResumeCache:
        cache = cls(run_key)
        cache.saved = dict(await durable.items(cache.kind))
        return cache

    def get(self, key: str) -> str | None:
        found = self.saved.get(key)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def keep(self, key: str, value: str) -> None:
        self.saved[key] = value
        durable.save_later(self.kind, key, value)

    # --- the three wrapped channels -----------------------------------------------------

    def http_client(self, timeout: float = 60.0) -> Any:
        """An HTTP client (sensors/caching.py) whose answers go through this cache."""
        from northvaine.sensors.caching import caching_client

        return caching_client(self, timeout)

    def fetcher(self, inner: Any) -> CachingPageFetcher:
        return CachingPageFetcher(inner, self)

    def llm(self) -> AbstractContextManager[None]:
        """Model calls inside the block go through the cache."""
        return llm.client_override(CachingLlmClient(llm.get_client(), self))


class CachingPageFetcher:
    """Wraps a page fetcher (radar.discover.LivePageFetcher); a fetch error is not saved."""

    def __init__(self, inner: Any, cache: ResumeCache) -> None:
        self.inner = inner
        self.cache = cache

    async def fetch(self, url: str) -> Any:
        from northvaine.radar.discover import UpgradedPage

        key = "page:" + request_hash(url)
        saved = self.cache.get(key)
        if saved is not None:
            return UpgradedPage.model_validate_json(saved)
        page = await self.inner.fetch(url)
        if getattr(page, "refused", None) != "error":
            self.cache.keep(key, page.model_dump_json())
        return page


class _Endpoint:
    def __init__(self, client: CachingLlmClient, kind: str) -> None:
        self.client = client
        self.kind = kind

    async def create(self, **body: Any) -> Any:
        return await self.client.answer(self.kind, body)


class CachingLlmClient:
    """Wraps the model client: a saved reply comes back with zero tokens (no cost)."""

    def __init__(self, inner: Any, cache: ResumeCache) -> None:
        self.inner = inner
        self.cache = cache
        self.chat = type("Chat", (), {})()
        self.chat.completions = _Endpoint(self, "chat")
        self.embeddings = _Endpoint(self, "embed")

    async def answer(self, kind: str, body: dict[str, Any]) -> Any:
        key = f"llm:{kind}:" + exchange_key(kind, _plain(body))
        saved = self.cache.get(key)
        if saved is not None:
            data = json.loads(saved)
            data["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            return _namespace(data)
        target = self.inner.chat.completions if kind == "chat" else self.inner.embeddings
        raw = await target.create(**body)
        try:
            self.cache.keep(key, json.dumps(_response_dict(kind, raw)))
        except Exception:  # an unusual reply shape is simply not saved
            logger.warning("model reply not saved for resume")
        return raw
