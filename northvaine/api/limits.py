"""Rate limits on the paid "Build my radar" steps (D146).

Each new session searches the web and each proposal calls the model, so a script hitting the public
page could spend the search credits and the day's model budget and lock every real visitor out.
Limits are per client address (the first `X-Forwarded-For` entry the host adds, else the socket
address) and per hour, kept in memory: a restart forgets them, which is fine for a free demo.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException, Request

WINDOW_SECONDS = 3600.0
PER_HOUR = {"start": 5, "propose": 10, "catalogue": 5}

_hits: dict[tuple[str, str], deque[float]] = {}


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def check(request: Request, action: str) -> None:
    """Raise 429 when this address has used `action` its hourly number of times."""
    now = time.monotonic()
    key = (client_address(request), action)
    hits = _hits.setdefault(key, deque())
    while hits and now - hits[0] > WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= PER_HOUR[action]:
        raise HTTPException(
            status_code=429, detail="Too many tries from here. Please wait a while and try again."
        )
    hits.append(now)
    if len(_hits) > 10_000:  # forget idle addresses so the table cannot grow without end
        for stale in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW_SECONDS]:
            del _hits[stale]


def reset() -> None:
    _hits.clear()
