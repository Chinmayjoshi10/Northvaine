"""Discover and lead upgrade (T5.3, D59, D65): sensors with shifted queries, then one publisher
page fetch per lead (robots, deny list, safe fetch, contacts stripped).

`http` is an httpx.AsyncClient or None; httpx is not imported here (network belongs in sensors/).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from northvaine.core.models import EvidenceDocument, EvidenceKind
from northvaine.core.settings import ConfigError, Settings, get_settings
from northvaine.radar.ledger import evidence_document_from_sensor
from northvaine.radar.models import ClientSpec, DiscoverResult, UpgradedPage
from northvaine.radar.verify import is_evidence_document
from northvaine.sensors.base import (
    FetchBlocked,
    RobotsDisallowed,
    SensorDocument,
    SensorError,
    SensorQuery,
    content_hash,
)
from northvaine.sensors.fetch import Resolver, RobotsCache, safe_fetch
from northvaine.sensors.html_text import extract_links, html_to_text
from northvaine.sensors.registry import get_sensor
from northvaine.sensors.replay import ReplayMismatch

__all__ = [
    "LivePageFetcher",
    "PageFetcher",
    "RecordedPageFetcher",
    "discover",
    "focus_queries",
    "prepare_queries",
    "shift_queries",
    "strip_contacts",
    "upgraded_document",
]

CONTACT_PLACEHOLDER = "[contact removed]"

# Copied from scripts/record_sensor_fixtures.py (the recorder's redaction patterns).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_PHONE_RES = (
    re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-()]*\d[\d\s.\-()]{6,}\d"),
    re.compile(r"(?<![\w.])\(\d{2,5}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\w.\-])0\d{1,4}[\s.\-/]\d{3,4}[\s.\-/]?\d{2,4}(?![\w\-])"),
)


def shift_queries(
    queries: dict[str, list[SensorQuery]], as_of: date
) -> dict[str, list[SensorQuery]]:
    """Shift every query's date range to end at `as_of`, keeping its length (D65).

    Both dates: same length, ends at `as_of`. Only `published_to`: moves to `as_of`. Anything
    else is unchanged. Returns copies; the input is not touched."""
    shifted: dict[str, list[SensorQuery]] = {}
    for sensor_name, items in queries.items():
        out: list[SensorQuery] = []
        for q in items:
            if q.published_from is not None and q.published_to is not None:
                span = q.published_to - q.published_from
                update = {"published_from": as_of - span, "published_to": as_of}
                out.append(q.model_copy(update=update))
            elif q.published_to is not None and q.published_from is None:
                out.append(q.model_copy(update={"published_to": as_of}))
            else:
                out.append(q.model_copy())
        shifted[sensor_name] = out
    return shifted


def focus_queries(
    queries: dict[str, list[SensorQuery]], settings: Settings
) -> dict[str, list[SensorQuery]]:
    """Point shifted queries at what a seller can still act on (D71).

    A query for an event the settings map to the tender stream looks back at most
    `radar_tender_lookback_days`, since a bidding window is about a month (D27). A query to an
    enumerable source asks for up to `radar_enumerable_max_results` records, so recent notices
    are not cut off by a small page. A query only for trade records keeps its own cap: the
    sensor ranks its importers, so the cap is a choice, not a page size (D102). Returns copies."""
    tender_kinds = {k for k, stream in settings.radar_stream_by_event.items() if stream == "tender"}
    trade_kinds = {k for k, stream in settings.radar_stream_by_event.items() if stream == "trade"}
    lookback = timedelta(days=settings.radar_tender_lookback_days)
    wanted = min(settings.radar_enumerable_max_results, settings.sensor_max_results)
    focused: dict[str, list[SensorQuery]] = {}
    for sensor_name, items in queries.items():
        out: list[SensorQuery] = []
        for q in items:
            update: dict[str, Any] = {}
            if (
                tender_kinds.intersection(q.kinds)
                and q.published_to is not None
                and (q.published_from is None or q.published_to - q.published_from > lookback)
            ):
                update["published_from"] = q.published_to - lookback
            trade_only = bool(q.kinds) and {k.value for k in q.kinds} <= trade_kinds
            if (
                sensor_name in settings.radar_enumerable_sources
                and q.max_results < wanted
                and not trade_only
            ):
                update["max_results"] = wanted
            out.append(q.model_copy(update=update))
        focused[sensor_name] = out
    return focused


def prepare_queries(
    queries: dict[str, list[SensorQuery]], as_of: date, settings: Settings
) -> dict[str, list[SensorQuery]]:
    """The queries a radar run sends: shifted to `as_of`, then focused."""
    return focus_queries(shift_queries(queries, as_of), settings)


STEERING_PLACEHOLDER = "[text aimed at AI systems removed]"
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*\s*|\n")


def neutralise_steering(text: str, settings: Settings | None = None) -> tuple[str, int]:
    """Remove every sentence that addresses AI systems or asks to be ranked, rated or marked
    (CLAUDE.md #10, D85). Returns the cleaned text and how many sentences were removed.
    Idempotent, so a replay rebuilds exactly what the live run used."""
    cfg = settings or get_settings()
    patterns = [re.compile(p, re.IGNORECASE) for p in cfg.radar_steering_patterns]
    removed = 0
    out: list[str] = []
    for part in _SENTENCE.findall(text):
        if STEERING_PLACEHOLDER in part or not any(p.search(part) for p in patterns):
            out.append(part)
            continue
        removed += 1
        trailing = part[len(part.rstrip()) :]
        out.append(STEERING_PLACEHOLDER + (trailing or " "))
    return "".join(out), removed


def strip_contacts(text: str) -> str:
    """Remove email addresses and phone numbers from fetched text (D59). Idempotent.

    Repeated until nothing changes: removing one number can expose the next ("01-00123+44020..."
    only shows "+44..." as a phone once the number before it is gone), and a live recording was
    refused for exactly that."""
    while True:
        cleaned = _EMAIL_RE.sub(CONTACT_PLACEHOLDER, text)
        for pattern in _PHONE_RES:
            cleaned = pattern.sub(CONTACT_PLACEHOLDER, cleaned)
        if cleaned == text:
            return cleaned
        text = cleaned


class PageFetcher(Protocol):
    """Fetches one lead's publisher page; a refusal is a result, never an exception."""

    async def fetch(self, url: str) -> UpgradedPage: ...


def _refusal(
    url: str,
    reason: str,
    *,
    final_url: str | None = None,
    status: int | None = None,
    fetched_at: datetime | None = None,
) -> UpgradedPage:
    return UpgradedPage(
        lead_url=url,
        final_url=final_url,
        status=status,
        fetched_at=fetched_at,
        title=None,
        text=None,
        refused=reason,
    )


class LivePageFetcher:
    """Real fetch: RobotsCache + safe_fetch + html_to_text + strip_contacts."""

    def __init__(
        self,
        client: Any = None,  # httpx.AsyncClient | None
        resolver: Resolver | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._settings = settings or get_settings()
        self._robots = RobotsCache()

    async def fetch(self, url: str) -> UpgradedPage:
        try:
            await self._robots.ensure_allowed(
                url, client=self._client, resolver=self._resolver, settings=self._settings
            )
            page = await safe_fetch(
                url, client=self._client, resolver=self._resolver, settings=self._settings
            )
        except RobotsDisallowed:
            return _refusal(url, "robots")
        except FetchBlocked:
            return _refusal(url, "denied")
        except Exception:  # one bad page must never stop a run
            return _refusal(url, "error")
        if page.status >= 300:
            return _refusal(
                url,
                f"http_{page.status}",
                final_url=page.final_url,
                status=page.status,
                fetched_at=page.fetched_at,
            )
        ctype = (page.content_type or "").lower()
        if ctype and "html" not in ctype and "text" not in ctype:
            return _refusal(
                url,
                "content_type",
                final_url=page.final_url,
                status=page.status,
                fetched_at=page.fetched_at,
            )
        title, text = html_to_text(page.text)
        return UpgradedPage(
            lead_url=url,
            final_url=page.final_url,
            status=page.status,
            fetched_at=page.fetched_at,
            title=strip_contacts(title) if title else title,  # titles carry phones too
            text=strip_contacts(text),
            refused=None,
            contact_text=text,
            links=[  # a link carrying an email or phone is dropped, never stored
                link
                for link in extract_links(page.text, page.final_url or url)
                if strip_contacts(link) == link
            ][: self._settings.radar_fit_link_cap],
        )


class RecordedPageFetcher:
    """Replay from a list of recorded pages; an unknown url raises ReplayMismatch."""

    def __init__(self, pages: list[UpgradedPage]) -> None:
        self._pages = {p.lead_url: p for p in pages}

    async def fetch(self, url: str) -> UpgradedPage:
        try:
            return self._pages[url]
        except KeyError:
            raise ReplayMismatch(f"no recorded page for {url}") from None


def upgraded_document(page: UpgradedPage, lead: EvidenceDocument) -> EvidenceDocument | None:
    """The `website` document for a fetched page (`available_at` = fetched_at, `meta.upgraded_from`
    = lead URL), or None when the page was refused or empty."""
    if page.refused is not None or page.text is None or not page.text.strip():
        return None
    claimed = lead.meta.get("published_on", lead.meta.get("published_date"))
    return EvidenceDocument(
        id=uuid5(NAMESPACE_URL, content_hash(page.text)),
        source_name="website",
        url=page.final_url or page.lead_url,
        title=page.title,
        text=page.text,
        available_at=page.fetched_at,
        workspace_id=None,
        meta={
            "upgraded_from": lead.url,
            "lead_source": lead.source_name,
            "claimed_published_on": claimed,
        },
    )


def _is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


async def discover(
    spec: ClientSpec,
    queries: dict[str, list[SensorQuery]],
    *,
    http: Any,  # httpx.AsyncClient | None; httpx stays out of radar imports (rule: sensors/)
    fetcher: PageFetcher,
    settings: Settings | None = None,
) -> DiscoverResult:
    """Run the sensors for `queries`, then upgrade up to `radar_max_lead_upgrades` leads."""
    settings = settings or get_settings()
    notes: list[str] = []
    collected: list[SensorDocument] = []
    # Which query found each snapshot, as "sensor:index" (1-based), so learning can credit
    # the searches that pay (D87). Keyed by content hash: duplicates add their query too.
    refs_by_hash: dict[str, list[str]] = {}
    for sensor_name, sensor_queries in queries.items():
        try:
            sensor = get_sensor(sensor_name, client=http, settings=settings)
        except (KeyError, ConfigError) as exc:
            notes.append(f"sensor {sensor_name}: {exc}")
            continue
        for i, query in enumerate(sensor_queries):
            try:
                result = await sensor.search(query)
            except (SensorError, ConfigError) as exc:
                notes.append(f"sensor {sensor_name} query {i + 1}: {type(exc).__name__}: {exc}")
                continue
            except ReplayMismatch:
                raise  # a replay that asks for something unrecorded is a bug, never a note
            except Exception as exc:  # a timeout or a dropped connection never stops a run
                notes.append(f"sensor {sensor_name} query {i + 1}: {type(exc).__name__}")
                continue
            collected.extend(result.documents)
            for sdoc in result.documents:
                refs = refs_by_hash.setdefault(sdoc.content_hash, [])
                ref = f"{sensor_name}:{i + 1}"
                if ref not in refs:
                    refs.append(ref)
            notes.extend(f"sensor {sensor_name} query {i + 1}: {n}" for n in result.notes)

    seen_hashes: set[str] = set()
    seen_urls: set[str] = set()
    seen_ids: set[UUID] = set()
    documents: list[EvidenceDocument] = []
    leads: list[EvidenceDocument] = []
    steered: list[str] = []
    found_by: dict[str, list[str]] = {}
    refs_by_url: dict[str, list[str]] = {}

    def unsteer(doc: EvidenceDocument) -> EvidenceDocument:
        if not doc.text:
            return doc
        clean, removed = neutralise_steering(doc.text, settings)
        if not removed:
            return doc
        steered.append(doc.url)
        notes.append(
            f"text aimed at AI systems removed from {doc.url} ({removed} sentence(s)); "
            "it never affects ranking (D85)"
        )
        return doc.model_copy(update={"text": clean})

    for sdoc in collected:
        refs_by_url.setdefault(sdoc.url, [])
        for ref in refs_by_hash.get(sdoc.content_hash, []):
            if ref not in refs_by_url[sdoc.url]:
                refs_by_url[sdoc.url].append(ref)
        if sdoc.content_hash in seen_hashes or sdoc.url in seen_urls:
            continue
        seen_hashes.add(sdoc.content_hash)
        seen_urls.add(sdoc.url)
        doc = evidence_document_from_sensor(sdoc)
        kind = is_evidence_document(doc, settings).kind
        if kind is not EvidenceKind.STRUCTURED and doc.text:
            # Search-result text is third-party page text: strip contacts before any model sees
            # it, as for fetched pages (D59). Structured records are rendered by code and their
            # quote check is a whole-line match, so they are left untouched.
            doc = unsteer(doc.model_copy(update={"text": strip_contacts(doc.text)}))
        found_by[str(doc.id)] = refs_by_url[sdoc.url]
        if kind is EvidenceKind.LEAD:
            leads.append(doc)
        else:
            documents.append(doc)
            seen_ids.add(doc.id)

    upgraded: list[UpgradedPage] = []
    candidates = [lead for lead in leads if _is_http(lead.url)]
    cap = settings.radar_max_lead_upgrades
    if len(candidates) > cap:
        notes.append(f"{len(candidates) - cap} lead(s) not upgraded: cap of {cap} reached")
    for lead in candidates[:cap]:
        page = await fetcher.fetch(lead.url)
        upgraded.append(page)
        doc = upgraded_document(page, lead)
        if doc is None or doc.id in seen_ids:
            continue
        seen_ids.add(doc.id)
        found_by[str(doc.id)] = list(refs_by_url.get(lead.url, []))
        documents.append(unsteer(doc))
    return DiscoverResult(
        documents=documents,
        leads=len(leads),
        upgraded=upgraded,
        notes=notes,
        steered_urls=sorted(set(steered)),
        found_by={k: v for k, v in found_by.items() if k in {str(d.id) for d in documents}},
    )
