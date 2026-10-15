"""UK Find a Tender (FTS) sensor: OCDS release packages as documents.

Confirmed shapes: docs/integrations/uk-find-a-tender-ocds-api-*.md. The API is free, keyless and
published under the Open Government Licence v3.0 (attribute: Find a Tender Service).

What this sensor does and does not do:
- `kinds` map to OCDS release tags. The API's own `stages` filter is NOT used: it silently drops
  every Procurement Act 2023 notice. Filtering by tag happens here, after the page is read.
- `codes` with the `cpv:` scheme are applied here (the API has no classification filter). Other
  schemes, `text` and `languages` are ignored. `countries` must include GB or nothing is fetched.
- Only fields this module reads are kept. `parties[].contactPoint` (names, emails, phones) is
  never read, rendered or stored, and free-text descriptions are not rendered.
- Output lines follow the TED rendering (ted.render_notice_text) where the meaning matches, so
  radar/structured.py can reuse its evidence path with the same `meta` keys.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qs, urlparse

from northvaine.core.models import EventType, SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.sensors.base import (
    DateFlag,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorRateLimited,
    SensorResult,
    content_hash,
)
from northvaine.sensors.dates import (
    available_at_for_publication,
    parse_date,
    validate_notice_dates,
)
from northvaine.sensors.ted import withhold_natural_persons

if TYPE_CHECKING:
    import httpx

FTS_API_URL = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
FTS_NOTICE_URL = "https://www.find-tender.service.gov.uk/Notice/{notice_id}"
FTS_MAX_LIMIT = 100
FTS_MIN_INTERVAL_SECONDS = 2.0
FTS_MAX_PAGES = 10  # one busy day is about six pages of 100
FTS_COUNTRY = "GB"
META_SCHEMA_VER = 1

# OCDS release tags -> the generic EventType. Planning, cancellation, termination and change
# tags are not tender or award events and are dropped. No client or industry word lives here.
FTS_TAG_TO_KIND: dict[str, EventType] = {
    "tender": EventType.TENDER_PUBLISHED,
    "tenderUpdate": EventType.TENDER_PUBLISHED,
    "award": EventType.CONTRACT_AWARDED,
    "awardUpdate": EventType.CONTRACT_AWARDED,
    "contract": EventType.CONTRACT_AWARDED,
    "contractUpdate": EventType.CONTRACT_AWARDED,
}
FTS_KIND_TO_TAGS: dict[EventType, tuple[str, ...]] = {
    EventType.TENDER_PUBLISHED: ("tender", "tenderUpdate"),
    EventType.CONTRACT_AWARDED: ("award", "awardUpdate", "contract", "contractUpdate"),
}
# OCDS `language` is ISO 639-1; TED's rendered lines use ISO 639-2 codes.
_LANG3 = {"en": "eng", "cy": "cym", "ga": "gle", "gd": "gla"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# The same phone patterns as radar.discover and the fixture recorder: a number in a title or a
# name is removed before anything stores it.
_PHONE_RES = (
    re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-()]*\d[\d\s.\-()]{6,}\d"),
    re.compile(r"(?<![\w.])\(\d{2,5}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\w.\-])0\d{1,4}[\s.\-/]\d{3,4}[\s.\-/]?\d{2,4}(?![\w\-])"),
)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_request(
    query: SensorQuery,
    *,
    as_of: datetime | None = None,
    cursor: str | None = None,
    settings: Settings | None = None,
) -> dict[str, str]:
    """The query parameters for a generic query. Order is stable: limit, window, cursor.

    The window is `updatedFrom`/`updatedTo` as `YYYY-MM-DDTHH:MM:SS` (no timezone). With
    `as_of`, the upper bound is min(published_to, as_of UTC date - ted_availability_lag_days),
    end of day, so nothing published on or after the as_of day is requested. Raises ValueError
    when no kind maps to an OCDS tag.
    """
    settings = settings or get_settings()
    if not any(kind in FTS_KIND_TO_TAGS for kind in query.kinds):
        raise ValueError("no query kind maps to an FTS release tag")
    params: dict[str, str] = {"limit": str(min(FTS_MAX_LIMIT, query.max_results))}
    if query.published_from is not None:
        params["updatedFrom"] = f"{query.published_from:%Y-%m-%d}T00:00:00"
    upper: date | None = query.published_to
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(UTC).date() - timedelta(days=settings.ted_availability_lag_days)
        upper = cutoff if upper is None else min(upper, cutoff)
    if upper is not None:
        params["updatedTo"] = f"{upper:%Y-%m-%d}T23:59:59"
    if cursor:
        params["cursor"] = cursor
    return params


# ----------------------------------------------------------------------------- release readers
# Only the paths below are read. Anything else in a release, contact points above all, is ignored.


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        text = _EMAIL.sub("[email removed]", " ".join(value.split()))
        for pattern in _PHONE_RES:
            text = pattern.sub("[phone removed]", text)
        return text
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def release_kind(release: dict[str, Any]) -> EventType | None:
    """The event kind of a release from its tags; award wins over tender when both appear."""
    kinds = {FTS_TAG_TO_KIND[t] for t in _list(release.get("tag")) if t in FTS_TAG_TO_KIND}
    if EventType.CONTRACT_AWARDED in kinds:
        return EventType.CONTRACT_AWARDED
    return EventType.TENDER_PUBLISHED if kinds else None


def _classifications(release: dict[str, Any]) -> list[str]:
    """CPV codes from every place the schema carries them, in first-seen order."""
    tender = _dict(release.get("tender"))
    holders: list[dict[str, Any]] = [_dict(tender.get("classification"))]
    sections = [tender, *[_dict(a) for a in _list(release.get("awards"))]]
    for section in sections:
        for item in _list(section.get("items")):
            holders.extend(_dict(c) for c in _list(_dict(item).get("additionalClassifications")))
    for award in _list(release.get("awards")):
        holders.extend(_dict(c) for c in _list(_dict(award).get("additionalClassifications")))
    return _unique(
        [str(h["id"]).strip() for h in holders if h.get("scheme") == "CPV" and h.get("id")]
    )


def _party_countries(release: dict[str, Any]) -> dict[str, str]:
    """party id -> ISO 3166-1 alpha-2 from the party address. Nothing else of a party is read."""
    result: dict[str, str] = {}
    for party in _list(release.get("parties")):
        party = _dict(party)
        country = _dict(party.get("address")).get("country")
        if party.get("id") and isinstance(country, str) and len(country) == 2:
            result[str(party["id"])] = country.upper()
    return result


def _notice_type(release: dict[str, Any]) -> str | None:
    """The notice type (UK4, UK7, F02...) of the document whose id is this release's id."""
    tender = _dict(release.get("tender"))
    docs = list(_list(tender.get("documents")))
    for contract in _list(release.get("contracts")):
        docs.extend(_list(_dict(contract).get("documents")))
    for doc in docs:
        doc = _dict(doc)
        if doc.get("noticeType") and doc.get("id") == release.get("id"):
            return str(doc["noticeType"])
    return None


def _money(amount: float, currency: str | None) -> str:
    return f"{amount:.2f} {currency}" if currency else f"{amount:.2f}"


def _names(release: dict[str, Any], settings: Settings) -> tuple[list[str], list[dict[str, Any]]]:
    """(buyer names, winners as {name, country, id}) with natural persons withheld (D76)."""
    countries = _party_countries(release)
    buyer = _dict(release.get("buyer"))
    buyer_names = [n for n in [_text(buyer.get("name"))] if n]
    winners: list[dict[str, Any]] = []
    seen: set[str] = set()
    for award in _list(release.get("awards")):
        for supplier in _list(_dict(award).get("suppliers")):
            supplier = _dict(supplier)
            name = _text(supplier.get("name"))
            if name and name not in seen:
                seen.add(name)
                winners.append({"name": name, "country": countries.get(str(supplier.get("id")))})
    # The TED helper works on these two field names; reuse it so the markers and the
    # placeholder are the same everywhere (D76).
    safe = withhold_natural_persons(
        {"buyer-name": buyer_names, "winner-name": [w["name"] for w in winners]}, settings
    )
    for winner, name in zip(winners, safe["winner-name"], strict=True):
        winner["name"] = name
    return safe["buyer-name"], winners


def render_release_text(release: dict[str, Any], *, settings: Settings | None = None) -> str:
    """Deterministic plain-text rendering of one release (D39), TED line formats where the
    meaning matches. The same release always gives byte-identical text; absent fields leave no
    line. Contact points and free-text descriptions are never rendered."""
    return _render(_extract(release, settings or get_settings()))


def _extract(release: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Every value the document needs, read once, so text and meta cannot disagree."""
    tender = _dict(release.get("tender"))
    buyers, winners = _names(release, settings)
    kind = release_kind(release)
    countries = _party_countries(release)
    buyer_country = countries.get(str(_dict(release.get("buyer")).get("id")))

    contracts = [_dict(c) for c in _list(release.get("contracts"))]
    title = _text(tender.get("title")) or next(
        (t for t in (_text(c.get("title")) for c in contracts) if t), None
    )

    estimates: list[str] = []
    if kind is EventType.TENDER_PUBLISHED:
        values = [_dict(lot.get("value")) for lot in map(_dict, _list(tender.get("lots")))]
        values = [v for v in values if _number(v.get("amount")) is not None]
        if not values and _number(_dict(tender.get("value")).get("amount")) is not None:
            values = [_dict(tender.get("value"))]
        for v in values:
            amount = _number(v.get("amount"))
            if amount:  # 0 is read as not stated, as on TED
                estimates.append(_money(amount, _text(v.get("currency"))))
        estimates = _unique(estimates)

    total: float | None = None
    total_currency: str | None = None
    notes: list[str] = []
    if kind is EventType.CONTRACT_AWARDED:
        values = [_dict(c.get("value")) for c in contracts]
        amounts = [(_number(v.get("amount")), _text(v.get("currency"))) for v in values]
        amounts = [(a, cur) for a, cur in amounts if a]
        # A framework release repeats one ceiling value per supplier, so a sum would overstate
        # it. A total is stated only when exactly one contract carries a value.
        if len(amounts) == 1:
            total, total_currency = amounts[0][0], amounts[0][1] or None
        elif len(amounts) > 1:
            notes.append("multiple_contract_values_total_not_stated")

    raw_deadlines = _unique(
        [str(v) for v in [_dict(tender.get("tenderPeriod")).get("endDate")] if v]
    )
    raw_signed = _unique([str(c["dateSigned"]) for c in contracts if c.get("dateSigned")])
    return {
        "id": release.get("id"),
        "ocid": release.get("ocid"),
        "tags": [str(t) for t in _list(release.get("tag"))],
        "kind": kind,
        "notice_type": _notice_type(release),
        "raw_publication": release.get("date"),
        "language": str(release.get("language") or "en"),
        "title": title,
        "buyers": buyers,
        "buyer_country": buyer_country,
        "winners": winners,
        "cpv": _classifications(release),
        # D94: the release's own category (goods/works/services), as the source states it
        "nature": _unique([str(tender.get("mainProcurementCategory"))])
        if tender.get("mainProcurementCategory")
        else [],
        "raw_deadlines": raw_deadlines,
        "raw_signed": raw_signed,
        "estimates": estimates,
        "total": total,
        "currency": total_currency,
        "legal_basis": _text(_dict(tender.get("legalBasis")).get("id")),
        "above_threshold": tender.get("aboveThreshold")
        if isinstance(tender.get("aboveThreshold"), bool)
        else None,
        "notes": notes,
    }


def _render(x: dict[str, Any]) -> str:
    lang = _LANG3.get(x["language"], x["language"])
    lines: list[str] = []
    if x["id"]:
        lines.append(f"Notice: {x['id']}" + (f" ({x['notice_type']})" if x["notice_type"] else ""))
    if x["ocid"]:
        lines.append(f"Procedure: {x['ocid']}")
    if x["raw_publication"]:
        lines.append(f"Published: {x['raw_publication']}")
    if x["title"]:
        lines.append(f"Title [{lang}]: {x['title']}")
    if x["buyers"]:
        lines.append(f"Buyer [{lang}]: {'; '.join(x['buyers'])}")
    if x["buyer_country"]:
        lines.append(f"Buyer country: {x['buyer_country']}")
    if x["winners"]:
        lines.append(f"Winner [{lang}]: {'; '.join(w['name'] for w in x['winners'])}")
        winner_countries = _unique([w["country"] for w in x["winners"] if w["country"]])
        if winner_countries:
            lines.append(f"Winner country: {', '.join(winner_countries)}")
    if x["cpv"]:
        lines.append(f"CPV: {', '.join(x['cpv'])}")
    if x["nature"]:
        lines.append(f"Contract nature: {', '.join(x['nature'])}")
    lines.extend(f"Deadline: {d}" for d in x["raw_deadlines"])
    # TED's "Winner decision date" is the award decision. FTS only carries the contract signing
    # date, which is a different event, so it gets its own label and structured.py ignores it.
    lines.extend(f"Contract signed: {d}" for d in x["raw_signed"])
    lines.extend(f"Estimated value (lot): {e}" for e in x["estimates"])
    if x["total"]:
        lines.append(f"Total value: {_money(x['total'], x['currency'])}")
    return "\n".join(lines)


def parse_release(
    release: dict[str, Any], *, fetched_at: datetime, settings: Settings | None = None
) -> SensorDocument:
    """One OCDS release to a SensorDocument with D36 availability and D38 date flags.

    `available_at` comes only from the release `date` (the official publication timestamp),
    never from signing, period or deadline fields. Dates are flagged, never corrected.
    Raises ValueError when the release has no id.
    """
    settings = settings or get_settings()
    if not release.get("id"):
        raise ValueError("FTS release has no id")
    x = _extract(release, settings)
    notice_id = str(x["id"])

    raw_publication = x["raw_publication"]
    publication = parse_date(raw_publication) if isinstance(raw_publication, str) else None
    deadlines = [parse_date(v) for v in x["raw_deadlines"]]
    signed = [parse_date(v) for v in x["raw_signed"]]
    flags = validate_notice_dates(
        publication, deadlines, signed, extreme_lag_days=settings.ted_extreme_lag_days
    )
    if raw_publication and publication is None and DateFlag.UNPARSEABLE not in flags:
        flags.insert(0, DateFlag.UNPARSEABLE)

    kind: EventType | None = x["kind"]
    lang = _LANG3.get(x["language"], x["language"])
    meta: dict[str, Any] = {
        "schema_ver": META_SCHEMA_VER,
        "notice_kind": kind.value if kind else None,
        "notice_type": x["notice_type"],
        "notice_subtype": None,
        "notice_version": None,
        "notice_identifier": notice_id,
        "ocid": x["ocid"],
        "tags": x["tags"],
        "buyers": x["buyers"],
        "buyer_countries": [x["buyer_country"]] if x["buyer_country"] else [],
        "winners": x["winners"],
        "cpv_codes": x["cpv"],
        "contract_nature": x["nature"],
        "deadlines": [d.isoformat() for d in dict.fromkeys(d for d in deadlines if d)],
        "winner_decision_dates": [],  # FTS has signing dates only; see contract_signed_dates
        "contract_signed_dates": [d.isoformat() for d in dict.fromkeys(d for d in signed if d)],
        "estimated_values": x["estimates"],
        "value": x["total"],
        "currency": x["currency"],
        "legal_basis": x["legal_basis"],
        "above_threshold": x["above_threshold"],
        "raw_dates": {
            "publication": raw_publication,
            "deadlines": x["raw_deadlines"],
            "winner_decisions": [],
            "contract_signed": x["raw_signed"],
        },
        "languages": [lang],
        "notes": x["notes"],
    }
    text = _render(x)
    available_at = (
        available_at_for_publication(publication, lag_days=settings.ted_availability_lag_days)
        if publication is not None
        else None
    )
    return SensorDocument(
        source=FtsSensor.name,
        tier=FtsSensor.tier,
        url=FTS_NOTICE_URL.format(notice_id=notice_id),
        title=x["title"],
        text=text,
        content_hash=content_hash(text),
        language=x["language"] if len(x["language"]) == 2 else None,
        published_on=publication,
        fetched_at=fetched_at,
        available_at=available_at,
        external_id=notice_id,
        group_key=str(x["ocid"]) if x["ocid"] else None,
        meta=meta,
        date_flags=flags,
    )


# ----------------------------------------------------------------------------- the sensor


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date form: treated as unstated


def _next_cursor(data: dict[str, Any]) -> str | None:
    """The `cursor` value inside `links.next`, or None on the last page."""
    link = _dict(data.get("links")).get("next")
    if not isinstance(link, str):
        return None
    values = parse_qs(urlparse(link).query).get("cursor")
    return values[0] if values else None


class FtsSensor:
    """UK Find a Tender notices as documents. Enumerable: a date window is a complete list."""

    name: ClassVar[str] = "fts"
    tier: ClassVar[SourceTier] = SourceTier.OFFICIAL
    enumerable: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        min_interval_seconds: float = FTS_MIN_INTERVAL_SECONDS,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._sleep = sleep or asyncio.sleep
        self._min_interval = min_interval_seconds
        self._last_call: float | None = None

    def _new_client(self) -> httpx.AsyncClient:
        import httpx  # lazy: importing this module needs no network library

        return httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)

    async def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await self._sleep(wait)
        self._last_call = time.monotonic()

    async def _get(self, client: httpx.AsyncClient, params: dict[str, str]) -> dict[str, Any]:
        await self._pace()
        response = await client.get(FTS_API_URL, params=params)
        if response.status_code in (429, 503):
            raise SensorRateLimited(
                f"FTS rate limit or outage (HTTP {response.status_code})",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            # The body is never echoed: it may carry anything. Status only.
            raise SensorError(f"FTS returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SensorError("FTS returned a response that is not JSON") from None
        if not isinstance(data, dict):
            raise SensorError("FTS returned an unexpected response shape")
        return data

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """Read pages from `cursor` (the API's own cursor string) until `max_results` documents
        of the wanted kinds, the last page, or FTS_MAX_PAGES. `next_cursor` continues."""
        if query.countries and FTS_COUNTRY not in query.countries:
            return SensorResult(
                enumerable=self.enumerable, notes=["FTS covers GB only: no GB in query countries"]
            )
        # Validate before any network use (raises ValueError for unmappable kinds).
        build_request(query, as_of=as_of, cursor=cursor, settings=self._settings)
        client = self._client or self._new_client()
        try:
            return await self._search(client, query, as_of, cursor)
        finally:
            if self._client is None:
                await client.aclose()

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: SensorQuery,
        as_of: datetime | None,
        cursor: str | None,
    ) -> SensorResult:
        fetched_at = datetime.now(UTC)
        wanted = set(query.kinds)
        cpv = {c.split(":", 1)[1] for c in query.codes if c.startswith("cpv:")}
        seen: set[str] = set()
        docs: list[SensorDocument] = []
        dropped_kind = dropped_cpv = dropped_late = dropped_undated = skipped = 0
        truncated = cut = False
        next_cursor: str | None = None
        for _ in range(FTS_MAX_PAGES):
            params = build_request(query, as_of=as_of, cursor=cursor, settings=self._settings)
            data = await self._get(client, params)
            for release in _list(data.get("releases")):
                release = _dict(release)
                if release.get("id") in seen:
                    continue
                seen.add(str(release.get("id")))
                kind = release_kind(release)
                if kind not in wanted:
                    dropped_kind += 1
                    continue
                try:
                    doc = parse_release(release, fetched_at=fetched_at, settings=self._settings)
                except ValueError:
                    skipped += 1
                    continue
                if cpv and not cpv.intersection(doc.meta["cpv_codes"]):
                    dropped_cpv += 1
                    continue
                if as_of is not None:
                    if doc.available_at is None:
                        dropped_undated += 1
                        continue
                    if doc.available_at > as_of:
                        dropped_late += 1
                        continue
                docs.append(doc)
            cursor = _next_cursor(data)
            if len(docs) >= query.max_results:
                cut = len(docs) > query.max_results
                del docs[query.max_results :]
                truncated = cut or cursor is not None
                next_cursor = None if cut else cursor
                break
            if cursor is None:
                break
        else:
            truncated = True  # page cap reached with more pages behind it
            next_cursor = cursor
        notes: list[str] = []
        if cut:
            notes.append("page cut at max_results; the rest of that page is not returned")
        if dropped_kind:
            notes.append(f"dropped {dropped_kind} release(s) that are not tender or award events")
        if dropped_cpv:
            notes.append(f"dropped {dropped_cpv} release(s) with no wanted cpv code")
        if dropped_late:
            notes.append(f"dropped {dropped_late} release(s) with available_at after as_of")
        if dropped_undated:
            notes.append(f"dropped {dropped_undated} release(s) with no date under as_of")
        if skipped:
            notes.append(f"skipped {skipped} release(s) with no id")
        return SensorResult(
            documents=docs,
            next_cursor=next_cursor,
            truncated=truncated,
            enumerable=self.enumerable,
            notes=notes,
        )
