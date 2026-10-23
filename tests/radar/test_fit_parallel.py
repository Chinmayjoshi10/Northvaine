"""company_fit reads companies concurrently, with the sequential loop's output and order."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from northvaine.core.settings import Settings
from northvaine.radar import fit as fit_module
from northvaine.radar.fit import company_fit
from northvaine.radar.models import RankedEntry, UpgradedPage
from northvaine.sensors.base import SensorDocument, SensorResult, SourceTier, content_hash
from tests.radar.test_fit import NOW, SPEC, entry

NAMES = [
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliet",
]


def _entries() -> list[RankedEntry]:
    out = []
    for i, name in enumerate(NAMES):
        e = entry("awarded_contractor")
        c = e.candidate.model_copy(update={"key": f"FR:{name.lower()}", "name": name})
        out.append(e.model_copy(update={"candidate": c, "rank": i + 1}))
    return out


class _Sensor:
    async def search(self, query: Any) -> SensorResult:
        name = query.text.split()[0].lower()
        url = f"https://www.{name}.fr/"
        doc = SensorDocument(
            source="tavily",
            tier=SourceTier.REPORTED,
            url=url,
            text="snippet",
            content_hash=content_hash(url),
            fetched_at=NOW,
            available_at=NOW,
        )
        return SensorResult(documents=[doc], notes=[], enumerable=False)


class _SlowFetcher:
    """Every page takes a while; earlier companies are slower, so they finish last."""

    async def fetch(self, url: str) -> UpgradedPage:
        host = url.split("/")[2]
        name = host.removeprefix("www.").split(".")[0]
        rank = [n.lower() for n in NAMES].index(name)
        await asyncio.sleep(0.05 + 0.01 * (len(NAMES) - rank))
        ok = url.rstrip("/").endswith(host)  # the home page only
        return UpgradedPage(
            lead_url=url,
            final_url=url,
            status=200 if ok else 404,
            fetched_at=NOW,
            title="t",
            text=f"{name} supplies granite for public squares and city streets. Contact us today."
            if ok
            else None,
            refused=None if ok else "http_404",
        )


async def _run(concurrency: int, monkeypatch: Any) -> tuple[list[dict[str, Any]], list[str], float]:
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: _Sensor())
    cfg = Settings(
        _env_file=None,
        radar_fit_concurrency=concurrency,
        radar_site_guess_max_companies=0,
        radar_fit_max_accounts=20,
    )
    started = time.perf_counter()
    out, notes = await company_fit(
        _entries(), SPEC, http=None, fetcher=_SlowFetcher(), as_of=NOW, settings=cfg
    )
    return [e.model_dump(mode="json") for e in out], notes, time.perf_counter() - started


async def test_parallel_is_faster_and_identical(monkeypatch: Any) -> None:
    slow, slow_notes, t_slow = await _run(1, monkeypatch)
    fast, fast_notes, t_fast = await _run(8, monkeypatch)
    assert fast == slow
    assert fast_notes == slow_notes
    assert all(e["company_site"] for e in fast), [
        e["company_site"] for e in fast
    ]  # the run did read pages
    assert t_fast < t_slow / 2


async def test_order_follows_the_input_even_when_later_companies_finish_first(
    monkeypatch: Any,
) -> None:
    out, _, _ = await _run(8, monkeypatch)
    assert [e["candidate"]["name"] for e in out] == NAMES
