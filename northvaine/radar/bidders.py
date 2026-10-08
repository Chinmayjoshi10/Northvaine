"""Likely bidders for open tenders (D81): who won similar awards in the same country recently.

Before an award, the organisation running a tender is a demand source, not the material buyer
(D80). The companies that keep winning the same kind of work in that country are the likely
bidders, and they price materials into their bids now (D23, the WOS field test). This step reads
official award notices for the tender's own classification codes and country, and verifies every
winner by code through the structured evidence path. It makes no model call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from northvaine.brain.budget import RunContext
from northvaine.core.models import EventConceptRow, EventType
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.ledger import build_evidence, evidence_document_from_sensor
from northvaine.radar.models import LikelyBidder, RadarStream, RankedEntry
from northvaine.sensors.base import SensorError, SensorQuery
from northvaine.sensors.registry import get_sensor

__all__ = ["bidder_query", "likely_bidders"]

_WINNER_PREFIX = "Winner ["
_AWARD = EventType.CONTRACT_AWARDED.value


def _tender_codes(entry: RankedEntry, settings: Settings) -> list[str]:
    """The tender's own classification codes, from its verified events' slots."""
    codes: list[str] = []
    for event in entry.candidate.events:
        raw = event.slots.get("cpv_codes")
        if isinstance(raw, str):
            for code in (c.strip() for c in raw.split(",")):
                if code and f"cpv:{code}" not in codes:
                    codes.append(f"cpv:{code}")
    return codes[: settings.radar_bidder_max_codes]


def bidder_query(entry: RankedEntry, as_of: datetime, settings: Settings) -> SensorQuery | None:
    """The award search for one open tender, or None when it lacks codes or a country."""
    if entry.candidate.stream != RadarStream.TENDER or not entry.candidate.country:
        return None
    codes = _tender_codes(entry, settings)
    if not codes:
        return None
    today = as_of.date()
    return SensorQuery(
        kinds=[EventType.CONTRACT_AWARDED],
        codes=codes,
        countries=[entry.candidate.country],
        published_from=today - timedelta(days=settings.radar_bidder_lookback_days),
        published_to=today,
        max_results=min(settings.radar_bidder_max_results, settings.sensor_max_results),
    )


async def _winners(
    query: SensorQuery,
    *,
    http: Any,
    concepts: list[EventConceptRow],
    run: RunContext,
    settings: Settings,
) -> list[LikelyBidder]:
    sensor = get_sensor("ted", client=http, settings=settings)
    result = await sensor.search(query)
    found: dict[str, LikelyBidder] = {}
    for sdoc in result.documents:
        doc = evidence_document_from_sensor(sdoc)
        ledger = await build_evidence(doc, concepts, [], run=run, settings=settings)
        verified = {c.fingerprint: c for c in ledger.checks if c.verified}
        for event in ledger.events:
            subject = event.subject
            if event.event_type != _AWARD or subject is None or subject.name.startswith("["):
                continue  # withheld natural persons are never listed (D76)
            quote = next(
                (
                    verified[f].draft.source_quote
                    for f in event.claim_fingerprints
                    if f in verified
                    and verified[f].draft.source_quote.startswith(_WINNER_PREFIX)
                    and subject.name in verified[f].draft.source_quote
                ),
                None,
            )
            if quote is None:
                continue  # no verified winner line: not shown (rule #2)
            key = subject.name.casefold()
            won: date | None = event.occurred_on
            prior = found.get(key)
            if prior is None:
                found[key] = LikelyBidder(
                    name=subject.name,
                    country=subject.country,
                    wins=1,
                    last_won=won,
                    source_url=doc.url,
                    quote=quote,
                )
                continue
            newer = won is not None and (prior.last_won is None or won > prior.last_won)
            found[key] = prior.model_copy(
                update={
                    "wins": prior.wins + 1,
                    **({"last_won": won, "source_url": doc.url, "quote": quote} if newer else {}),
                }
            )
    ranked = sorted(
        found.values(),
        key=lambda b: (-b.wins, -(b.last_won.toordinal() if b.last_won else 0), b.name),
    )
    return ranked[: settings.radar_bidder_max]


async def likely_bidders(
    entries: list[RankedEntry],
    *,
    as_of: datetime,
    http: Any,
    concepts: list[EventConceptRow],
    run: RunContext,
    settings: Settings | None = None,
) -> tuple[list[RankedEntry], list[str]]:
    """Each tender entry with its likely bidders; notes for queries skipped or failed.

    One award search per distinct (codes, country), in rank order, capped by
    `radar_bidder_max_queries`. A failed search is a note, never a failed run."""
    cfg = settings or get_settings()
    notes: list[str] = []
    cache: dict[tuple[tuple[str, ...], tuple[str, ...]], list[LikelyBidder]] = {}
    out: list[RankedEntry] = []
    skipped = 0
    for entry in sorted(entries, key=lambda e: e.rank):
        query = bidder_query(entry, as_of, cfg)
        if query is None:
            out.append(entry)
            continue
        key = (tuple(query.codes), tuple(query.countries))
        if key not in cache:
            if len(cache) >= cfg.radar_bidder_max_queries:
                skipped += 1
                out.append(entry)
                continue
            try:
                cache[key] = await _winners(
                    query, http=http, concepts=concepts, run=run, settings=cfg
                )
            except SensorError as exc:
                notes.append(f"likely bidders not found for {entry.candidate.name}: {exc}")
                cache[key] = []
        out.append(entry.model_copy(update={"likely_bidders": cache[key]}))
    if skipped:
        notes.append(f"likely bidders not searched for {skipped} tender(s): query cap reached")
    return out, notes
