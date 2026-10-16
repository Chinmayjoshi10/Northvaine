"""The one place outside a sensor class that makes an HTTP client (invariant: network access
belongs in sensors/). Radar and API code ask for a client here and pass it to sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

__all__ = ["new_client"]


def new_client(timeout: float = 60.0) -> httpx.AsyncClient:
    import httpx  # lazy: importing this module needs no network library

    return httpx.AsyncClient(timeout=timeout)
