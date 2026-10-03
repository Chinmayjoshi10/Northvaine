"""Record/replay HTTP transport for sensor tests (T3.0b).

Replay has no network path: an unmatched request raises ReplayMismatch.
Recording never stores request headers, so credentials cannot be saved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

KEPT_HEADERS = ("content-type", "retry-after")


class ReplayMismatch(AssertionError):  # noqa: N818 - name fixed by the PLAN.md contract
    """A request had no (remaining) recorded exchange."""


class RecordedExchange(BaseModel):
    method: str
    url: str
    request_json: Any | None = None
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body_json: Any | None = None
    body_text: str | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        return value


def load_exchanges(path: str | Path) -> list[RecordedExchange]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RecordedExchange.model_validate(item) for item in raw]


def save_exchanges(path: str | Path, exchanges: list[RecordedExchange]) -> None:
    data = [e.model_dump(mode="json") for e in exchanges]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_json(content: bytes) -> Any | None:
    if not content:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def replay_transport(
    exchanges: list[RecordedExchange], *, match_body: bool = True
) -> httpx.MockTransport:
    """Serve recorded exchanges; identical requests are served in recorded order."""
    remaining = list(exchanges)

    def handler(request: httpx.Request) -> httpx.Response:
        sent = _parse_json(request.content)
        url = str(request.url)
        for i, ex in enumerate(remaining):
            if ex.method.upper() != request.method.upper() or ex.url != url:
                continue
            if match_body and ex.request_json != sent:
                continue
            remaining.pop(i)
            headers = dict(ex.headers)
            if ex.body_json is not None:
                headers.setdefault("content-type", "application/json")
                return httpx.Response(
                    ex.status, headers=headers, content=json.dumps(ex.body_json).encode()
                )
            return httpx.Response(ex.status, headers=headers, content=(ex.body_text or "").encode())
        raise ReplayMismatch(
            f"no recorded exchange left for {request.method} {url} (body={sent!r})"
        )

    return httpx.MockTransport(handler)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wraps a transport, returns its responses unchanged, and records each exchange."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.exchanges: list[RecordedExchange] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        await response.aread()
        body_json = _parse_json(response.content)
        body_text = None if body_json is not None else response.text
        self.exchanges.append(
            RecordedExchange(
                method=request.method,
                url=str(request.url),
                request_json=_parse_json(request.content),
                status=response.status_code,
                headers={k: response.headers[k] for k in KEPT_HEADERS if k in response.headers},
                body_json=body_json,
                body_text=body_text,
                recorded_at=datetime.now(UTC),
            )
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
