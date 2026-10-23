"""Bulk postcode lookup at postcodes.io (D126): free, no key, open data (Open Government Licence).

`POST {base}/postcodes` with `{"postcodes": [...]}`, at most 100 a request; the reply is
`{"status": 200, "result": [{"query": "<postcode>", "result": {...latitude, longitude...} | null}]}`
(https://postcodes.io/docs/postcode/bulk). Coordinates are rounded to 2 decimals (about a
district), so nothing is placed more precisely than that.
"""

from __future__ import annotations

from typing import Any

from northvaine.sensors.base import SensorError

__all__ = ["BATCH", "geocode_postcodes"]

BATCH = 100


async def geocode_postcodes(
    postcodes: list[str], *, base_url: str, client: Any, timeout: float
) -> dict[str, tuple[float, float]]:
    """{postcode: (lat, lon)} for those found. Raises SensorError on any failure."""
    import httpx  # lazy: importing this module needs no network library

    owned = client is None
    http = httpx.AsyncClient(timeout=timeout) if owned else client
    out: dict[str, tuple[float, float]] = {}
    try:
        for i in range(0, len(postcodes), BATCH):
            try:
                response = await http.post(
                    base_url.rstrip("/") + "/postcodes",
                    json={"postcodes": postcodes[i : i + BATCH]},
                )
                if response.status_code >= 400:
                    raise SensorError(f"postcodes.io returned HTTP {response.status_code}")
                body = response.json()
            except httpx.HTTPError as exc:
                raise SensorError(f"postcodes.io request failed: {type(exc).__name__}") from None
            except ValueError:
                raise SensorError("postcodes.io returned a response that is not JSON") from None
            items = body.get("result") if isinstance(body, dict) else None
            for item in items if isinstance(items, list) else []:
                found = item.get("result") if isinstance(item, dict) else None
                if not isinstance(found, dict):
                    continue
                lat, lon = found.get("latitude"), found.get("longitude")
                if isinstance(lat, int | float) and isinstance(lon, int | float):
                    out[str(item.get("query"))] = (round(lat, 2), round(lon, 2))
    finally:
        if owned:
            await http.aclose()
    return out
